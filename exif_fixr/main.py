from datetime import datetime
from pathlib import Path
import click
from tqdm import tqdm
from loguru import logger
import sys

from exif_fixr.processor import MediaProcessor

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
@click.option('--output-dir', type=click.Path(),
              help='Directory to save modified files. If not specified, original files will be modified.')
def main(directory: str, dry_run: bool, media_type: str, log_dir: str, output_dir: str):
    """Restore metadata to Google Takeout media files from their JSON files."""
    # Setup logging
    log_dir_path = Path(log_dir)
    log_dir_path.mkdir(exist_ok=True)
    setup_logging(log_dir_path)
    
    directory_path = Path(directory)
    output_dir_path = Path(output_dir) if output_dir else None
    
    # Create output directory if specified
    if output_dir_path:
        output_dir_path.mkdir(parents=True, exist_ok=True)
        logger.info(f"Output directory: {output_dir_path}")
    
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
    
    logger.info(f"Found {len(media_files)} files (with {formats = }) to process")
    
    # Process files
    success_count = 0
    failed_files = []
    with tqdm(total=len(media_files), desc='Processing media files') as pbar:
        for media_path in media_files:
            if processor.process_file(media_path, None, dry_run, output_dir_path):
                success_count += 1
            else:
                failed_files.append(media_path)
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
