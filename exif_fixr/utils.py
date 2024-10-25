
import os
from pathlib import Path
import re
from typing import Optional, Tuple


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
