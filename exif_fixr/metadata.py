from datetime import datetime
from typing import Dict, Any

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
