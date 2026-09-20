import os
import sys
import unittest
import time

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import app

class YTDownloaderIntegrationTestCase(unittest.TestCase):
    def setUp(self):
        self.app = app.app
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()

    def test_fetch_info_and_download_short(self):
        # Using a reliable short public YouTube video
        # e.g., YouTube's official short test video "YouTube Test Video" or rickroll / me at the zoo
        # "Me at the zoo" is 19 seconds: id "jNQXAC9IVRw"
        url = "https://www.youtube.com/watch?v=jNQXAC9IVRw"
        
        print("\nTesting /api/info...")
        res = self.client.post('/api/info', json={'url': url})
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data.get('type'), 'video')
        self.assertEqual(data.get('video_id'), 'jNQXAC9IVRw')
        self.assertTrue(len(data.get('resolutions', [])) > 0)
        print(f"Info retrieved successfully: {data.get('title')}")

        print("\nTesting /api/download with 5-second audio trim...")
        dl_res = self.client.post('/api/download', json={
            'url': url,
            'format_type': 'mp3',
            'bitrate': '128',
            'start_time': 0,
            'end_time': 5,
            'embed_metadata': True
        })
        self.assertEqual(dl_res.status_code, 200)
        dl_data = dl_res.get_json()
        download_id = dl_data.get('download_id')
        self.assertIsNotNone(download_id)
        print(f"Download enqueued: {download_id}")

        # Poll status until finished
        max_wait = 30
        start = time.time()
        finished = False
        final_status = None
        while time.time() - start < max_wait:
            time.sleep(1.5)
            status_res = self.client.get('/api/active')
            self.assertEqual(status_res.status_code, 200)
            active = status_res.get_json()
            if download_id in active:
                item = active[download_id]
                status = item.get('status')
                pct = item.get('progress')
                st_text = item.get('status_text')
                print(f"Status: {status} ({pct}%) - {st_text}")
                if status in ('completed', 'error'):
                    final_status = status
                    finished = True
                    break

        self.assertTrue(finished, "Download did not finish within timeout")
        self.assertEqual(final_status, 'completed')

        # Check history
        hist_res = self.client.get('/api/history')
        self.assertEqual(hist_res.status_code, 200)
        hist = hist_res.get_json()
        found = next((h for h in hist if h.get('download_id') == download_id), None)
        self.assertIsNotNone(found)
        self.assertTrue(found.get('file_exists'), "Downloaded file should exist on disk")
        filepath = found.get('filepath')
        print(f"File downloaded successfully to: {filepath}")
        self.assertTrue(os.path.exists(filepath))
        self.assertTrue(os.path.getsize(filepath) > 0)

        # Test streaming file by ID
        stream_res = self.client.get(f'/api/files/by-id/{download_id}')
        self.assertEqual(stream_res.status_code, 200)
        print("Streaming by ID verified successfully.")

if __name__ == '__main__':
    unittest.main()
