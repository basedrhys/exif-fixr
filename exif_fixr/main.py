import os
import json
import subprocess
from datetime import datetime
from pathlib import Path
import click
from tqdm import tqdm
from PIL import Image
import piexif
import ffmpeg
from typing import Optional, Dict, Any, Tuple, Set, Protocol, Union, List
from loguru import logger
import sys
import re

def normalize_filename(filename: str) -> Tuple[str, str, Optional[int]]:
    """
    Normalize filename by separating base name, extension, and duplicate number.
    Examples:
        IMG_4869.HEIC -> (IMG_4869, .HEIC, None)
        IMG_4869(1).HEIC -> (IMG_4869, .HEIC, 1)
        IMG_4869.HEIC(1) -> (IMG_4869, .HEIC, 1)
    """
    # Extract extension
    base, ext = os.path.splitext(filename)
    
    # Check for duplicate number in two formats:
    # 1. before extension: name(1).ext
    # 2. after extension: name.ext(1)
    dup_pattern = r'(?:\((\d+)\))'
    
    # Check for number before extension
    pre_match = re.search(f'{dup_pattern}$', base)
    if pre_match:
        return base[:pre_match.start()], ext, int(pre_match.group(1))
    
    # Check for number after extension
    post_match = re.search(dup_pattern, ext)
    if post_match:
        return base, ext[:post_match.start()], int(post_match.group(1))
    
    return base, ext, None

def find_matching_json(media_path: Path) -> Optional[Path]:
    """Find matching JSON file for a media file, handling duplicate numbers."""
    base, ext, dup_num = normalize_filename(media_path.name)
    
    # List of possible JSON filename patterns
    possible_patterns = [
        f"{base}{ext}.json",  # Basic case: IMG_4869.HEIC.json
        f"{base}.{ext[1:]}({dup_num}).json" if dup_num else None,  # After extension: IMG_4869.HEIC(1).json
        f"{base}({dup_num}){ext}.json" if dup_num else None  # Before extension: IMG_4869(1).HEIC.json
    ]
    
    # Remove None values
    patterns = [p for p in possible_patterns if p]
    
    # Check each possible pattern
    for pattern in patterns:
        json_path = media_path.parent / pattern
        if json_path.exists():
            return json_path
    
    return None

class MediaMetadata:
    """Data class to store parsed metadata."""
    def __init__(self, json_data: Dict[str, Any]):
        # Extract timestamp
        photo_time = json_data.get('photoTakenTime', {})
        self.timestamp = photo_time.get('timestamp')
        self.formatted_time = (
            datetime.fromtimestamp(int(self.timestamp)).isoformat()
            if self.timestamp else None
        )
        
        # Extract GPS data
        geo_data = json_data.get('geoData', {})
        self.latitude = geo_data.get('latitude')
        self.longitude = geo_data.get('longitude')
        self.altitude = geo_data.get('altitude')
        
        # Extract other metadata
        self.title = json_data.get('title')
        self.description = json_data.get('description')

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
    
    def apply_metadata(self, file_path: Path, metadata: MediaMetadata, dry_run: bool) -> bool:
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

class MediaProcessor:
    """Main processor for handling media files."""
    
    def __init__(self):
        self.handlers = {
            'image': (ImageHandler(), {'.jpg', '.jpeg', '.heic', '.png'}),
            'video': (VideoHandler(), {'.mp4', '.mov', '.avi', '.m4v'})
        }
        self.supported_formats = {
            ext for _, formats in self.handlers.values() for ext in formats
        }

    def get_handler(self, file_path: Path) -> Optional[Tuple[MediaHandler, str]]:
        """Get appropriate handler for the file type."""
        suffix = file_path.suffix.lower()
        for media_type, (handler, formats) in self.handlers.items():
            if suffix in formats:
                return handler, media_type
        return None

    def process_file(self, file_path: Path, json_path: Optional[Path], dry_run: bool) -> bool:
        """Process a single media file."""
        try:
            handler_info = self.get_handler(file_path)
            if not handler_info:
                logger.warning(f"Unsupported format: {file_path}")
                return False

            handler, media_type = handler_info

            # Use the new find_matching_json function if no JSON path is provided
            if not json_path:
                json_path = find_matching_json(file_path)
            
            if not json_path or not json_path.exists():
                logger.warning(f"No JSON metadata found for: {file_path}")
                return False

            with open(json_path, 'r') as f:
                json_data = json.load(f)

            metadata = MediaMetadata(json_data)
            return handler.apply_metadata(file_path, metadata, dry_run)

        except Exception as e:
            logger.error(f"Error processing {file_path}: {e}")
            return False

def setup_logging(log_dir: Path):
    """Configure loguru logger."""
    logger.remove()  # Remove default handler
    
    # Add colored stdout handler
    logger.add(
        sys.stdout,
        colorize=True,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>"
    )
    
    # Add file handler
    log_file = log_dir / f"metadata_restore_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    logger.add(
        log_file,
        rotation="100 MB",
        retention="1 week",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {message}"
    )

@click.command()
@click.argument('directory', type=click.Path(exists=True))
@click.option('--dry-run', is_flag=True, help='Run without applying changes')
@click.option('--type', 'media_type', type=click.Choice(['all', 'images', 'videos']), 
              default='all', help='Type of media files to process')
@click.option('--log-dir', type=click.Path(), default='logs',
              help='Directory to store log files')
def main(directory: str, dry_run: bool, media_type: str, log_dir: str):
    """Restore metadata to Google Takeout media files from their JSON files."""
    # Setup logging
    log_dir_path = Path(log_dir)
    log_dir_path.mkdir(exist_ok=True)
    setup_logging(log_dir_path)
    
    directory_path = Path(directory)
    processor = MediaProcessor()
    
    logger.info(f"Starting metadata restoration in: {directory}")
    logger.info(f"Dry run: {dry_run}")
    logger.info(f"Media type: {media_type}")
    
    # Filter formats based on media type
    formats = processor.supported_formats
    if media_type == 'images':
        formats = processor.handlers['image'][1]
    elif media_type == 'videos':
        formats = processor.handlers['video'][1]
    
    # Find all media files
    media_files = []
    for ext in formats:
        media_files.extend(directory_path.rglob(f'*{ext}'))
    
    logger.info(f"Found {len(media_files)} files to process")
    
    # Process files
    success_count = 0
    with tqdm(total=len(media_files), desc='Processing media files') as pbar:
        for media_path in media_files:
            if processor.process_file(media_path, None, dry_run):
                success_count += 1
            pbar.update(1)
    
    # Log summary
    logger.info("\nProcessing Summary:")
    logger.info(f"Total files processed: {len(media_files)}")
    logger.info(f"Successfully processed: {success_count}")
    logger.info(f"Skipped/Failed: {len(media_files) - success_count}")
    if dry_run:
        logger.info("This was a dry run - no changes were applied.")

if __name__ == '__main__':
    main()