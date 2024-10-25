import os
import json
import subprocess
from datetime import datetime
from pathlib import Path
import click
from tqdm import tqdm
from PIL import Image
from PIL.ExifTags import TAGS, GPSTAGS
import piexif
import ffmpeg
from typing import Optional, Dict, Any, Tuple, Set

class MetadataProcessor:
    """Handles the processing of metadata from JSON to EXIF/video metadata format."""
    
    @staticmethod
    def convert_timestamp_to_exif(timestamp: str) -> bytes:
        """Convert Unix timestamp to EXIF datetime format."""
        dt = datetime.fromtimestamp(int(timestamp))
        return dt.strftime("%Y:%m:%d %H:%M:%S").encode('utf-8')
    
    @staticmethod
    def convert_geo_to_exif(lat: float, lon: float, alt: float) -> Dict:
        """Convert decimal GPS coordinates to EXIF format."""
        def decimal_to_dms(decimal: float) -> Tuple[Tuple[int, int], Tuple[int, int], Tuple[int, int]]:
            degrees = int(decimal)
            minutes = int((decimal - degrees) * 60)
            seconds = int(((decimal - degrees) * 60 - minutes) * 60 * 100)
            return ((degrees, 1), (minutes, 1), (seconds, 100))

        lat_ref = 'N' if lat >= 0 else 'S'
        lon_ref = 'E' if lon >= 0 else 'W'
        lat = abs(lat)
        lon = abs(lon)

        gps_ifd = {
            piexif.GPSIFD.GPSLatitudeRef: lat_ref.encode('utf-8'),
            piexif.GPSIFD.GPSLatitude: decimal_to_dms(lat),
            piexif.GPSIFD.GPSLongitudeRef: lon_ref.encode('utf-8'),
            piexif.GPSIFD.GPSLongitude: decimal_to_dms(lon),
        }

        if alt is not None:
            alt_ref = 0 if alt >= 0 else 1
            gps_ifd[piexif.GPSIFD.GPSAltitudeRef] = alt_ref
            gps_ifd[piexif.GPSIFD.GPSAltitude] = (int(abs(alt) * 100), 100)

        return gps_ifd

    def create_exif_dict(self, metadata: Dict[str, Any]) -> Dict:
        """Create EXIF dictionary from JSON metadata."""
        exif_dict = {'0th': {}, '1st': {}, 'Exif': {}, 'GPS': {}, 'Interop': {}}

        # Add creation time
        if 'photoTakenTime' in metadata:
            timestamp = metadata['photoTakenTime']['timestamp']
            exif_dict['Exif'][piexif.ExifIFD.DateTimeOriginal] = self.convert_timestamp_to_exif(timestamp)
            exif_dict['0th'][piexif.ImageIFD.DateTime] = self.convert_timestamp_to_exif(timestamp)

        # Add GPS data if available
        if 'geoData' in metadata:
            geo = metadata['geoData']
            if all(k in geo for k in ['latitude', 'longitude']):
                exif_dict['GPS'] = self.convert_geo_to_exif(
                    geo['latitude'],
                    geo['longitude'],
                    geo.get('altitude')
                )

        return exif_dict

class MediaProcessor:
    """Handles the processing of media files (images and videos)."""
    
    def __init__(self, metadata_processor: MetadataProcessor):
        self.metadata_processor = metadata_processor
        self.image_formats = {'.jpg', '.jpeg', '.heic', '.png'}
        self.video_formats = {'.mp4', '.mov', '.avi', '.m4v'}
        self.supported_formats = self.image_formats | self.video_formats

    def process_media(self, media_path: Path, json_path: Optional[Path], dry_run: bool = False) -> bool:
        """Process a single media file and its corresponding JSON metadata."""
        try:
            # Check if media format is supported
            if media_path.suffix.lower() not in self.supported_formats:
                return False

            # If no JSON file exists, skip
            if not json_path or not json_path.exists():
                return False

            # Read metadata from JSON
            with open(json_path, 'r') as f:
                metadata = json.load(f)

            if media_path.suffix.lower() in self.image_formats:
                return self._process_image(media_path, metadata, dry_run)
            else:
                return self._process_video(media_path, metadata, dry_run)

        except Exception as e:
            print(f"Error processing {media_path}: {str(e)}")
            return False

    def _process_image(self, image_path: Path, metadata: Dict[str, Any], dry_run: bool) -> bool:
        """Process an image file."""
        exif_dict = self.metadata_processor.create_exif_dict(metadata)
        
        if not dry_run:
            exif_bytes = piexif.dump(exif_dict)
            piexif.insert(exif_bytes, str(image_path))

        return True

    def _process_video(self, video_path: Path, metadata: Dict[str, Any], dry_run: bool) -> bool:
        """Process a video file."""
        if dry_run:
            return True

        try:
            # Create temporary file path
            temp_path = video_path.with_name(f"{video_path.stem}_temp{video_path.suffix}")
            
            # Prepare metadata arguments for FFmpeg
            metadata_args = []
            
            # Add creation time
            if 'photoTakenTime' in metadata:
                creation_time = datetime.fromtimestamp(int(metadata['photoTakenTime']['timestamp']))
                metadata_args.extend([
                    '-metadata', f"creation_time={creation_time.isoformat()}"
                ])

            # Add GPS data
            if 'geoData' in metadata:
                geo = metadata['geoData']
                if all(k in geo for k in ['latitude', 'longitude']):
                    metadata_args.extend([
                        '-metadata', f"location={geo['latitude']},{geo['longitude']}"
                    ])

            # Skip if no metadata to add
            if not metadata_args:
                return True

            # Build FFmpeg command
            command = [
                'ffmpeg', '-i', str(video_path),
                '-c', 'copy',  # Copy without re-encoding
                *metadata_args,
                '-y',  # Overwrite output file if exists
                str(temp_path)
            ]

            # Run FFmpeg
            result = subprocess.run(command, capture_output=True, text=True)
            if result.returncode != 0:
                raise Exception(f"FFmpeg error: {result.stderr}")

            # Replace original file with the new one
            os.replace(temp_path, video_path)
            return True

        except Exception as e:
            print(f"Error processing video {video_path}: {str(e)}")
            # Clean up temporary file if it exists
            if temp_path.exists():
                temp_path.unlink()
            return False

def find_json_path(media_path: Path) -> Optional[Path]:
    """Find the corresponding JSON file for a media file."""
    json_path = media_path.with_suffix(media_path.suffix + '.json')
    return json_path if json_path.exists() else None

@click.command()
@click.argument('directory', type=click.Path(exists=True))
@click.option('--dry-run', is_flag=True, help='Run without applying changes')
@click.option('--type', 'media_type', type=click.Choice(['all', 'images', 'videos']), 
              default='all', help='Type of media files to process')
def main(directory: str, dry_run: bool, media_type: str):
    """Restore metadata to Google Takeout media files from their JSON files."""
    directory_path = Path(directory)
    metadata_processor = MetadataProcessor()
    media_processor = MediaProcessor(metadata_processor)
    
    # Determine which formats to process based on media_type
    if media_type == 'images':
        formats = media_processor.image_formats
    elif media_type == 'videos':
        formats = media_processor.video_formats
    else:
        formats = media_processor.supported_formats
    
    # Find all media files recursively
    media_files = []
    for ext in formats:
        media_files.extend(directory_path.rglob(f'*{ext}'))
    
    # Process each media file
    success_count = 0
    with tqdm(total=len(media_files), desc='Processing media files') as pbar:
        for media_path in media_files:
            json_path = find_json_path(media_path)
            if media_processor.process_media(media_path, json_path, dry_run):
                success_count += 1
            pbar.update(1)
    
    # Print summary
    total_files = len(media_files)
    print(f"\nSummary:")
    print(f"Total files processed: {total_files}")
    print(f"Successfully processed: {success_count}")
    print(f"Skipped/Failed: {total_files - success_count}")
    if dry_run:
        print("\nThis was a dry run - no changes were applied.")

if __name__ == '__main__':
    main()