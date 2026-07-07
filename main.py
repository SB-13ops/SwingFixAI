<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>SwingFix AI - Upload from Phone</title>
<link href="https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@700;800&family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    background: #0C1409; color: #e8f0d8;
    font-family: 'Inter', sans-serif;
    min-height: 100vh; padding: 24px 20px;
  }
  .logo { font-family: 'Barlow Condensed', sans-serif; font-size: 26px; font-weight: 800; text-align: center; margin-bottom: 4px; }
  .logo span { color: #7CBD1E; }
  .sub { text-align: center; font-size: 13px; color: #9aaf7a; margin-bottom: 28px; }
  .slot {
    background: #1e2b16; border: 1px solid rgba(124,189,30,0.2);
    border-radius: 14px; padding: 18px; margin-bottom: 14px;
    position: relative;
  }
  .slot.done { border-color: #7CBD1E; }
  .slot-title { font-size: 15px; font-weight: 600; margin-bottom: 4px; }
  .slot-desc { font-size: 12px; color: #9aaf7a; margin-bottom: 12px; }
  .slot-btns { display: flex; gap: 8px; }
  .btn {
    flex: 1; padding: 12px; border-radius: 8px; border: none;
    font-size: 14px; font-weight: 600; cursor: pointer;
    font-family: 'Inter', sans-serif;
  }
  .btn-record { background: #7CBD1E; color: #0a1007; }
  .btn-pick { background: transparent; color: #9aaf7a; border: 1px solid rgba(124,189,30,0.3); }
  .check { position: absolute; top: 14px; right: 16px; color: #7CBD1E; font-size: 20px; display: none; }
  .slot.done .check { display: block; }
  .progress {
    height: 4px; background: #243318; border-radius: 2px;
    margin-top: 10px; overflow: hidden; display: none;
  }
  .progress-fill { height: 100%; background: #7CBD1E; width: 0%; transition: width 0.3s; }
  .status { text-align: center; font-size: 13px; color: #9aaf7a; margin-top: 24px; line-height: 1.6; }
  .done-msg {
    display: none; text-align: center; margin-top: 24px;
    background: rgba(124,189,30,0.1); border: 1px solid #7CBD1E;
    border-radius: 12px; padding: 20px; font-size: 14px; line-height: 1.6;
  }
</style>
</head>
<body>

<div class="logo">Swing<span>Fix</span> AI</div>
<div class="sub">Upload your swing videos - they appear on your computer instantly</div>

<div class="slot" id="slot-faceon">
  <span class="check">&#10003;</span>
  <div class="slot-title">1. Face-on view</div>
  <div class="slot-desc">Camera facing your chest, full body in frame</div>
  <div class="slot-btns">
    <button class="btn btn-record" onclick="pick('faceon', true)">Record</button>
    <button class="btn btn-pick" onclick="pick('faceon', false)">Camera roll</button>
  </div>
  <div class="progress" id="prog-faceon"><div class="progress-fill" id="fill-faceon"></div></div>
</div>

<div class="slot" id="slot-dtl">
  <span class="check">&#10003;</span>
  <div class="slot-title">2. Down-the-line view</div>
  <div class="slot-desc">Camera behind you, looking down the target line</div>
  <div class="slot-btns">
    <button class="btn btn-record" onclick="pick('dtl', true)">Record</button>
    <button class="btn btn-pick" onclick="pick('dtl', false)">Camera roll</button>
  </div>
  <div class="progress" id="prog-dtl"><div class="progress-fill" id="fill-dtl"></div></div>
</div>

<div class="slot" id="slot-front">
  <span class="check">&#10003;</span>
  <div class="slot-title">3. Front-facing view</div>
  <div class="slot-desc">Camera facing your back, down the line from the other side</div>
  <div class="slot-btns">
    <button class="btn btn-record" onclick="pick('front', true)">Record</button>
    <button class="btn btn-pick" onclick="pick('front', false)">Camera roll</button>
  </div>
  <div class="progress" id="prog-front"><div class="progress-fill" id="fill-front"></div></div>
</div>

<div class="status" id="status">Upload at least one view, then return to your computer.</div>
<div class="done-msg" id="doneMsg">
  <strong>All videos uploaded!</strong><br>
  Return to your computer - your videos are ready to analyze.
</div>

<input type="file" id="picker" accept="video/*" style="display:none">

<script>
var SESSION_ID = window.location.pathname.split('/').pop();
var uploaded = { faceon: false, dtl: false, front: false };
var currentSlot = null;

function pick(slot, useCamera) {
  currentSlot = slot;
  var input = document.getElementById('picker');
  input.value = '';
  if (useCamera) input.setAttribute('capture', 'environment');
  else input.removeAttribute('capture');
  input.click();
}

document.getElementById('picker').addEventListener('change', function() {
  var file = this.files[0];
  if (!file || !currentSlot) return;
  uploadFile(currentSlot, file);
});

function uploadFile(slot, file) {
  var prog = document.getElementById('prog-' + slot);
  var fill = document.getElementById('fill-' + slot);
  prog.style.display = 'block';

  var formData = new FormData();
  formData.append('slot', slot);
  formData.append('file', file, file.name);

  var xhr = new XMLHttpRequest();
  xhr.open('POST', '/api/session/' + SESSION_ID + '/upload');
  xhr.upload.onprogress = function(e) {
    if (e.lengthComputable) fill.style.width = (e.loaded / e.total * 100) + '%';
  };
  xhr.onload = function() {
    if (xhr.status === 200) {
      uploaded[slot] = true;
      document.getElementById('slot-' + slot).classList.add('done');
      prog.style.display = 'none';
      updateStatus();
    } else {
      document.getElementById('status').textContent = 'Upload failed - try again.';
      prog.style.display = 'none';
    }
  };
  xhr.onerror = function() {
    document.getElementById('status').textContent = 'Upload failed - check your WiFi connection.';
    prog.style.display = 'none';
  };
  xhr.send(formData);
}

function updateStatus() {
  var count = Object.values(uploaded).filter(Boolean).length;
  if (count === 3) {
    document.getElementById('status').style.display = 'none';
    document.getElementById('doneMsg').style.display = 'block';
  } else {
    document.getElementById('status').textContent =
      count + ' of 3 uploaded. Your computer sees them instantly - upload more or return to your desktop.';
  }
}
</script>
</body>
</html>
