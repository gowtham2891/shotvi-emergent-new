# Face detector model

`blaze_face_short_range.tflite` is required by `services/vertical_cropper.py`
for MediaPipe's Tasks API face detection (the legacy `mp.solutions.face_detection`
API isn't included in pip's Windows/cp311 mediapipe wheels).

Not checked into git (binary asset). If missing, download it with:

```
curl -L -o services/models/blaze_face_short_range.tflite "https://storage.googleapis.com/mediapipe-models/face_detector/blaze_face_short_range/float16/latest/blaze_face_short_range.tflite"
```
