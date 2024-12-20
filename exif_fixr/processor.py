from pathlib import Path
from typing import Optional, Tuple
import json
from loguru import logger

from exif_fixr.metadata import MediaMetadata
from exif_fixr.handlers import MediaHandler, ImageHandler, VideoHandler
from exif_fixr.utils import find_matching_json

class MediaProcessor:
    """Main processor for handling media files."""
    
    def __init__(self):
        self.handlers = {
            'image': (ImageHandler(), {'.jpg', '.jpeg', '.heic', '.png', '.tif', '.tiff'}),
            'video': (VideoHandler(), {'.mp4', '.mov', '.avi', '.m4v'})
        }
        # Add uppercase versions of extensions to supported formats
        for _, (_, formats) in self.handlers.items():
            uppercase_formats = {ext.upper() for ext in formats}
            formats.update(uppercase_formats)
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

    def process_file(self, file_path: Path, json_path: Optional[Path], dry_run: bool, output_dir: Optional[Path] = None) -> bool:
        """Process a single media file."""
        try:
            handler_info = self.get_handler(file_path)
            if not handler_info:
                logger.warning(f"Unsupported format: {file_path}")
                return False

            handler, media_type = handler_info

            # Use the find_matching_json function if no JSON path is provided
            if not json_path:
                json_path = find_matching_json(file_path)
            
            if not json_path or not json_path.exists():
                logger.warning(f"No JSON metadata found for: {file_path}")
                return False

            with open(json_path, 'r') as f:
                json_data = json.load(f)

            metadata = MediaMetadata(json_data)
            return handler.apply_metadata(file_path, metadata, dry_run, output_dir)

        except Exception as e:
            logger.error(f"Error processing {file_path}: {e}")
            return False
