import os
import json
from datetime import datetime
from pathlib import Path
import click
from tqdm import tqdm
from PIL import Image
from PIL.ExifTags import TAGS, GPSTAGS
import piexif
from typing import Optional, Dict, Any, Tuple

class MetadataProcessor:
    """Handles the processing of metadata from JSON to EXIF format."""
    
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

class ImageProcessor:
    """Handles the processing of image files."""
    
    def __init__(self, metadata_processor: MetadataProcessor):
        self.metadata_processor = metadata_processor
        self.supported_formats = {'.jpg', '.jpeg', '.heic', '.png'}

    def process_image(self, image_path: Path, json_path: Optional[Path], dry_run: bool = False) -> bool:
        """Process a single image and its corresponding JSON metadata."""
        try:
            # Check if image format is supported
            if image_path.suffix.lower() not in self.supported_formats:
                return False

            # If no JSON file exists, skip
            if not json_path or not json_path.exists():
                return False

            # Read metadata from JSON
            with open(json_path, 'r') as f:
                metadata = json.load(f)

            # Create EXIF dictionary
            exif_dict = self.metadata_processor.create_exif_dict(metadata)
            
            if not dry_run:
                # Convert to bytes and apply to image
                exif_bytes = piexif.dump(exif_dict)
                piexif.insert(exif_bytes, str(image_path))

            return True

        except Exception as e:
            print(f"Error processing {image_path}: {str(e)}")
            return False

def find_json_path(image_path: Path) -> Optional[Path]:
    """Find the corresponding JSON file for an image."""
    json_path = image_path.with_suffix(image_path.suffix + '.json')
    return json_path if json_path.exists() else None

@click.command()
@click.argument('directory', type=click.Path(exists=True))
@click.option('--dry-run', is_flag=True, help='Run without applying changes')
def main(directory: str, dry_run: bool):
    """Restore metadata to Google Takeout photos from their JSON files."""
    directory_path = Path(directory)
    metadata_processor = MetadataProcessor()
    image_processor = ImageProcessor(metadata_processor)
    
    # Find all image files recursively
    image_files = []
    for ext in image_processor.supported_formats:
        image_files.extend(directory_path.rglob(f'*{ext}'))
    
    # Process each image
    success_count = 0
    with tqdm(total=len(image_files), desc='Processing images') as pbar:
        for image_path in image_files:
            json_path = find_json_path(image_path)
            if image_processor.process_image(image_path, json_path, dry_run):
                success_count += 1
            pbar.update(1)
    
    # Print summary
    total_files = len(image_files)
    print(f"\nSummary:")
    print(f"Total files processed: {total_files}")
    print(f"Successfully processed: {success_count}")
    print(f"Skipped/Failed: {total_files - success_count}")
    if dry_run:
        print("\nThis was a dry run - no changes were applied.")

if __name__ == '__main__':
    main()