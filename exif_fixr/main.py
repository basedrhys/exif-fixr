import os
import json
from datetime import datetime
from pathlib import Path
import click
from tqdm import tqdm
from loguru import logger
import sys
import re
from typing import Optional, Tuple

from .metadata import MediaMetadata
from .handlers import ImageHandler, VideoHandler
from .processor import MediaProcessor

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
