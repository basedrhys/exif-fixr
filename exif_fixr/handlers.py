from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, Tuple, Protocol
import subprocess
import os
import piexif
from loguru import logger

from exif_fixr.metadata import MediaMetadata

class MediaHandler(Protocol):
    """Protocol defining interface for media handlers."""
    def apply_metadata(self, file_path: Path, metadata: MediaMetadata, dry_run: bool) -> bool:
        """Apply metadata to the media file."""
        ...

class ImageHandler:
    """Handles metadata application for image files."""
    
    @staticmethod
    def _convert_to_exif_time(timestamp: str) -> bytes:
        """Convert Unix timestamp to EXIF datetime format."""
        dt = datetime.fromtimestamp(int(timestamp))
        return dt.strftime("%Y:%m:%d %H:%M:%S").encode('utf-8')

    @staticmethod
    def _convert_to_exif_gps(lat: float, lon: float, alt: Optional[float]) -> Dict:
        """Convert decimal GPS coordinates to EXIF format."""
        def decimal_to_dms(decimal: float) -> Tuple[Tuple[int, int], Tuple[int, int], Tuple[int, int]]:
            degrees = int(decimal)
            minutes = int((decimal - degrees) * 60)
            seconds = int(((decimal - degrees) * 60 - minutes) * 60 * 100)
            return ((degrees, 1), (minutes, 1), (seconds, 100))

        lat_ref = 'N' if lat >= 0 else 'S'
        lon_ref = 'E' if lon >= 0 else 'W'
        
        gps_ifd = {
            piexif.GPSIFD.GPSLatitudeRef: lat_ref.encode('utf-8'),
            piexif.GPSIFD.GPSLatitude: decimal_to_dms(abs(lat)),
            piexif.GPSIFD.GPSLongitudeRef: lon_ref.encode('utf-8'),
            piexif.GPSIFD.GPSLongitude: decimal_to_dms(abs(lon)),
        }

        if alt is not None:
            alt_ref = 0 if alt >= 0 else 1
            gps_ifd[piexif.GPSIFD.GPSAltitudeRef] = alt_ref
            gps_ifd[piexif.GPSIFD.GPSAltitude] = (int(abs(alt) * 100), 100)

        return gps_ifd

    def apply_metadata(self, file_path: Path, metadata: MediaMetadata, dry_run: bool) -> bool:
        """Apply metadata to image file using EXIF."""
        try:
            exif_dict = {'0th': {}, '1st': {}, 'Exif': {}, 'GPS': {}, 'Interop': {}}

            # Add timestamps
            if metadata.timestamp:
                exif_time = self._convert_to_exif_time(metadata.timestamp)
                exif_dict['Exif'][piexif.ExifIFD.DateTimeOriginal] = exif_time
                exif_dict['0th'][piexif.ImageIFD.DateTime] = exif_time

            # Add GPS data
            if all(x is not None for x in [metadata.latitude, metadata.longitude]):
                exif_dict['GPS'] = self._convert_to_exif_gps(
                    metadata.latitude,
                    metadata.longitude,
                    metadata.altitude
                )

            if not dry_run:
                exif_bytes = piexif.dump(exif_dict)
                piexif.insert(exif_bytes, str(file_path))

            return True

        except Exception as e:
            logger.error(f"Failed to process image {file_path.name}: {e}")
            return False

class VideoHandler:
    """Handles metadata application for video files."""
    
    def apply_metadata(self, file_path: Path, metadata: 'MediaMetadata', dry_run: bool) -> bool:
        """Apply metadata to video file using FFmpeg."""
        if dry_run:
            return True

        temp_path = file_path.with_name(f"{file_path.stem}_temp{file_path.suffix}")
        try:
            metadata_args = []
            
            # Add creation time
            if metadata.formatted_time:
                metadata_args.extend([
                    '-metadata', f"creation_time={metadata.formatted_time}"
                ])

            # Add GPS data
            if metadata.latitude is not None and metadata.longitude is not None:
                metadata_args.extend([
                    '-metadata', f"location={metadata.latitude},{metadata.longitude}"
                ])

            if not metadata_args:
                logger.warning(f"No metadata to add for video: {file_path.name}")
                return True

            command = [
                'ffmpeg', '-i', str(file_path),
                '-c', 'copy',
                *metadata_args,
                '-y',
                str(temp_path)
            ]

            result = subprocess.run(command, capture_output=True, text=True)
            if result.returncode != 0:
                raise Exception(f"FFmpeg error: {result.stderr}")

            os.replace(temp_path, file_path)
            return True

        except Exception as e:
            logger.error(f"Failed to process video {file_path.name}: {e}")
            if temp_path.exists():
                temp_path.unlink()
            return False
