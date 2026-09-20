import os
import sys
import unittest
import json

# Ensure project directory is in sys.path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import app

class YTDownloaderBackendTestCase(unittest.TestCase):
    def setUp(self):
        self.app = app.app
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()

    def test_parse_youtube_url(self):
        # Standard watch URL
        vid, pl_id = app.parse_youtube_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        self.assertEqual(vid, "dQw4w9WgXcQ")
        self.assertIsNone(pl_id)

        # Short URL without protocol
        vid, pl_id = app.parse_youtube_url("youtu.be/dQw4w9WgXcQ")
        self.assertEqual(vid, "dQw4w9WgXcQ")

        # YouTube Shorts URL
        vid, pl_id = app.parse_youtube_url("https://www.youtube.com/shorts/3jz_eZfHpsI")
        self.assertEqual(vid, "3jz_eZfHpsI")

        # Music YouTube URL
        vid, pl_id = app.parse_youtube_url("https://music.youtube.com/watch?v=dQw4w9WgXcQ")
        self.assertEqual(vid, "dQw4w9WgXcQ")

        # Video in Playlist (Combination URL)
        vid, pl_id = app.parse_youtube_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=PLrEnWoR732-DNd23qTgiE_wG_ErhdfwzG")
        self.assertEqual(vid, "dQw4w9WgXcQ")
        self.assertEqual(pl_id, "PLrEnWoR732-DNd23qTgiE_wG_ErhdfwzG")

        # Pure Playlist URL
        vid, pl_id = app.parse_youtube_url("https://www.youtube.com/playlist?list=PLrEnWoR732-DNd23qTgiE_wG_ErhdfwzG")
        self.assertIsNone(vid)
        self.assertEqual(pl_id, "PLrEnWoR732-DNd23qTgiE_wG_ErhdfwzG")

    def test_ffmpeg_detection(self):
        has_ffmpeg = app.check_ffmpeg()
        ffmpeg_loc = app.get_ffmpeg_location()
        self.assertTrue(has_ffmpeg, "FFmpeg should be detected in workspace or PATH")
        self.assertIsNotNone(ffmpeg_loc)
        self.assertTrue(os.path.exists(ffmpeg_loc) or os.path.exists(os.path.join(ffmpeg_loc, 'ffmpeg.exe')))

    def test_api_config(self):
        res = self.client.get('/api/config')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn('is_local', data)
        self.assertIn('has_ffmpeg', data)

    def test_api_settings(self):
        res = self.client.get('/api/settings')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn('locations', data)
        # Verify active/default location exists in locations
        default_loc = next((loc for loc in data['locations'] if loc.get('is_default')), None)
        self.assertIsNotNone(default_loc)

    def test_api_history_file_exists_field(self):
        res = self.client.get('/api/history')
        self.assertEqual(res.status_code, 200)
        history = res.get_json()
        self.assertIsInstance(history, list)
        for item in history:
            self.assertIn('file_exists', item)
            self.assertIsInstance(item['file_exists'], bool)

    def test_parse_time_to_seconds(self):
        # Numerical 0 and 0.0
        self.assertEqual(app.parse_time_to_seconds(0), 0.0)
        self.assertEqual(app.parse_time_to_seconds(0.0), 0.0)

        # String 0 and formatted timestamps
        self.assertEqual(app.parse_time_to_seconds("0"), 0.0)
        self.assertEqual(app.parse_time_to_seconds("00:00"), 0.0)
        self.assertEqual(app.parse_time_to_seconds("00:30"), 30.0)
        self.assertEqual(app.parse_time_to_seconds("01:30"), 90.0)
        self.assertEqual(app.parse_time_to_seconds("01:04:30"), 3870.0)
        self.assertEqual(app.parse_time_to_seconds("1.30"), 90.0)
        self.assertEqual(app.parse_time_to_seconds("45.5"), 45.5)

        # None, empty, and invalid formats
        self.assertIsNone(app.parse_time_to_seconds(None))
        self.assertIsNone(app.parse_time_to_seconds(""))
        self.assertIsNone(app.parse_time_to_seconds("   "))
        self.assertIsNone(app.parse_time_to_seconds("invalid_time"))

    def test_api_download_trim_validation(self):
        # Valid start_time=0 and end_time=10
        res = self.client.post('/api/download', json={
            'url': 'https://www.youtube.com/watch?v=dQw4w9WgXcQ',
            'start_time': 0,
            'end_time': 10
        })
        self.assertEqual(res.status_code, 200)
        self.assertIn('download_id', res.get_json())

        # Valid string "00:00" and "00:15"
        res = self.client.post('/api/download', json={
            'url': 'https://www.youtube.com/watch?v=dQw4w9WgXcQ',
            'start_time': '00:00',
            'end_time': '00:15'
        })
        self.assertEqual(res.status_code, 200)

        # Negative start time
        res = self.client.post('/api/download', json={
            'url': 'https://www.youtube.com/watch?v=dQw4w9WgXcQ',
            'start_time': -5,
            'end_time': 10
        })
        self.assertEqual(res.status_code, 400)
        self.assertIn('error', res.get_json())

        # Start time >= End time
        res = self.client.post('/api/download', json={
            'url': 'https://www.youtube.com/watch?v=dQw4w9WgXcQ',
            'start_time': 20,
            'end_time': 10
        })
        self.assertEqual(res.status_code, 400)
        self.assertIn('error', res.get_json())

        # End time <= 0
        res = self.client.post('/api/download', json={
            'url': 'https://www.youtube.com/watch?v=dQw4w9WgXcQ',
            'start_time': 0,
            'end_time': 0
        })
        self.assertEqual(res.status_code, 400)

    def test_api_files_by_id_missing(self):
        res = self.client.get('/api/files/by-id/nonexistent_id')
        self.assertEqual(res.status_code, 404)

if __name__ == '__main__':
    unittest.main()
