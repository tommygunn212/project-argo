/**
 * ARGO Input Shell - Frontend Logic (v1.4.3)
 */
let mediaRecorder = null;
let audioChunks = [];
let isRecording = false;

async function apiCall(endpoint, method = 'GET', body = null) {
    const options = { method: method, headers: { 'Content-Type': 'application/json' } };
    if (body) options.body = JSON.stringify(body);
    const response = await fetch(endpoint, options);
    if (!response.ok) {
        const error = await response.json();
        throw new Error(error.detail || 'API Error');
    }
    return await response.json();
}

async function updateStatus() {
    try {
        const status = await apiCall('/api/status');
        document.getElementById('session-info').innerHTML = `Session: ${status.session_id.substring(0, 8)}... | Transcript: ${status.has_transcript ? '✓' : '○'} | Intent: ${status.has_intent ? '✓' : '○'} | Plan: ${status.has_plan ? '✓' : '○'}`;
        document.getElementById('transcription-stage').style.display = status.has_transcript ? 'block' : 'none';
        document.getElementById('intent-stage').style.display = status.has_intent ? 'block' : 'none';
        document.getElementById('plan-stage').style.display = status.has_plan ? 'block' : 'none';
        document.getElementById('execution-stage').style.display = status.has_plan ? 'block' : 'none';
        if (status.execution_log.length > 0) {
            document.getElementById('output-stage').style.display = 'block';
            const logBox = document.getElementById('execution-log');
            logBox.innerHTML = '';
            status.execution_log.forEach(entry => {
                const div = document.createElement('div');
                div.className = 'log-entry';
                if (entry.action.includes('ERROR')) div.classList.add('error');
                if (entry.action.includes('SUCCESS')) div.classList.add('success');
                const time = new Date(entry.timestamp).toLocaleTimeString();
                div.textContent = `[${time}] ${entry.action}`;
                logBox.appendChild(div);
            });
            logBox.scrollTop = logBox.scrollHeight;
        }
    } catch (e) {
        console.error('Status update error:', e);
    }
}

async function startRecording() {
    if (isRecording) return;
    const statusDiv = document.getElementById('recording-status');
    const pttBtn = document.getElementById('ptt-button');
    const cancelBtn = document.getElementById('ptt-cancel');
    
    cancelBtn.style.display = 'inline-block';
    pttBtn.classList.add('recording');
    statusDiv.textContent = '🔴 Recording...';
    
    try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        mediaRecorder = new MediaRecorder(stream);
        audioChunks = [];
        mediaRecorder.ondataavailable = (event) => { if (event.data.size > 0) audioChunks.push(event.data); };
        mediaRecorder.start();
        isRecording = true;
    } catch (error) {
        statusDiv.textContent = `Error: ${error.message}`;
        pttBtn.classList.remove('recording');
        cancelBtn.style.display = 'none';
        isRecording = false;
    }
}

async function stopRecording() {
    if (!isRecording || !mediaRecorder) return;
    const statusDiv = document.getElementById('recording-status');
    const pttBtn = document.getElementById('ptt-button');
    const cancelBtn = document.getElementById('ptt-cancel');
    
    return new Promise((resolve) => {
        mediaRecorder.onstop = async () => {
            mediaRecorder.stream.getTracks().forEach(track => track.stop());
            pttBtn.classList.remove('recording');
            cancelBtn.style.display = 'none';
            isRecording = false;
            
            const mimeType = mediaRecorder.mimeType || 'audio/webm';
            const audioBlob = new Blob(audioChunks, { type: mimeType });
            
            if (audioBlob.size === 0) {
                statusDiv.textContent = 'No audio';
                resolve();
                return;
            }
            
            statusDiv.textContent = 'Processing...';
            const formData = new FormData();
            formData.append('file', audioBlob, 'recording.webm');
            
            try {
                const response = await fetch('/api/transcribe', { method: 'POST', body: formData });
                if (!response.ok) {
                    const error = await response.json();
                    statusDiv.textContent = `Error: ${error.detail}`;
                    resolve();
                    return;
                }
                const result = await response.json();
                statusDiv.textContent = `✓ "${result.transcript}"`;
                document.getElementById('transcript-display').textContent = result.transcript;
                await updateStatus();
            } catch (e) {
                statusDiv.textContent = `Error: ${e.message}`;
            }
            resolve();
        };
        mediaRecorder.stop();
    });
}

function cancelRecording() {
    if (!isRecording) return;
    const statusDiv = document.getElementById('recording-status');
    const pttBtn = document.getElementById('ptt-button');
    const cancelBtn = document.getElementById('ptt-cancel');
    
    if (mediaRecorder) {
        mediaRecorder.onstop = null;
        mediaRecorder.stop();
        mediaRecorder.stream.getTracks().forEach(track => track.stop());
    }
    
    audioChunks = [];
    isRecording = false;
    mediaRecorder = null;
    pttBtn.classList.remove('recording');
    cancelBtn.style.display = 'none';
    statusDiv.textContent = 'Cancelled';
}

document.addEventListener('DOMContentLoaded', async () => {
    console.log('ARGO v1.4.3 initialized');
    const pttBtn = document.getElementById('ptt-button');
    const cancelBtn = document.getElementById('ptt-cancel');
    
    if (pttBtn) {
        pttBtn.addEventListener('mousedown', (e) => { e.preventDefault(); startRecording(); });
        pttBtn.addEventListener('mouseup', (e) => { e.preventDefault(); stopRecording(); });
        pttBtn.addEventListener('mouseleave', (e) => { if (isRecording) stopRecording(); });
        pttBtn.addEventListener('touchstart', (e) => { e.preventDefault(); startRecording(); });
        pttBtn.addEventListener('touchend', (e) => { e.preventDefault(); stopRecording(); });
        document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && isRecording) cancelRecording(); });
    }
    
    if (cancelBtn) cancelBtn.addEventListener('click', cancelRecording);
    
    const textInput = document.getElementById('text-input');
    if (textInput) {
        textInput.addEventListener('keypress', async (e) => {
            if (e.key === 'Enter') {
                const text = e.target.value.trim();
                if (!text) return;
                document.getElementById('transcript-display').textContent = text;
                document.getElementById('recording-status').textContent = `Text: "${text}"`;
                e.target.value = '';
                await updateStatus();
            }
        });
    }
    
    document.getElementById('confirm-transcript').addEventListener('click', async () => {
        try {
            const result = await apiCall('/api/confirm-transcript', 'POST');
            if (result.status === 'qa_answered') {
                document.getElementById('answer-stage').style.display = 'block';
                document.getElementById('answer-display').textContent = result.answer_text;
                document.getElementById('intent-stage').style.display = 'none';
                document.getElementById('plan-stage').style.display = 'none';
                document.getElementById('execution-stage').style.display = 'none';
            } else {
                document.getElementById('answer-stage').style.display = 'none';
                document.getElementById('intent-display').textContent = JSON.stringify(result.intent, null, 2);
            }
            await updateStatus();
        } catch (e) {
            alert('Error: ' + e.message);
        }
    });
    
    document.getElementById('reject-transcript').addEventListener('click', async () => {
        try {
            await apiCall('/api/reject-transcript', 'POST');
            document.getElementById('transcript-display').textContent = '';
            document.getElementById('transcription-stage').style.display = 'none';
            document.getElementById('intent-stage').style.display = 'none';
            document.getElementById('plan-stage').style.display = 'none';
            document.getElementById('execution-stage').style.display = 'none';
            document.getElementById('answer-stage').style.display = 'none';
            await updateStatus();
        } catch (e) {
            alert('Error: ' + e.message);
        }
    });
    
    document.getElementById('confirm-intent').addEventListener('click', async () => {
        try {
            const result = await apiCall('/api/confirm-intent', 'POST');
            document.getElementById('plan-display').textContent = JSON.stringify(result.plan, null, 2);
            await updateStatus();
        } catch (e) {
            alert('Error: ' + e.message);
        }
    });
    
    document.getElementById('reject-intent').addEventListener('click', async () => {
        try {
            await apiCall('/api/reject-intent', 'POST');
            document.getElementById('intent-display').textContent = '';
            document.getElementById('intent-stage').style.display = 'none';
            document.getElementById('plan-stage').style.display = 'none';
            document.getElementById('execution-stage').style.display = 'none';
            await updateStatus();
        } catch (e) {
            alert('Error: ' + e.message);
        }
    });
    
    document.getElementById('confirm-plan').addEventListener('click', async () => {
        try {
            await apiCall('/api/confirm-plan', 'POST');
            await updateStatus();
        } catch (e) {
            alert('Error: ' + e.message);
        }
    });
    
    document.getElementById('abort-plan').addEventListener('click', async () => {
        try {
            await apiCall('/api/abort-plan', 'POST');
            document.getElementById('plan-display').textContent = '';
            document.getElementById('plan-stage').style.display = 'none';
            document.getElementById('execution-stage').style.display = 'none';
            await updateStatus();
        } catch (e) {
            alert('Error: ' + e.message);
        }
    });
    
    document.getElementById('execute-button').addEventListener('click', async () => {
        try {
            const result = await apiCall('/api/execute', 'POST');
            if (result.result) {
                const logBox = document.getElementById('execution-log');
                const entry = document.createElement('div');
                entry.className = 'log-entry success';
                entry.textContent = `✓ Done: ${result.result.execution_status}`;
                logBox.appendChild(entry);
            }
            await updateStatus();
        } catch (e) {
            alert('Error: ' + e.message);
        }
    });
    
    document.getElementById('abort-execute').addEventListener('click', async () => {
        try {
            await apiCall('/api/abort-plan', 'POST');
            document.getElementById('plan-stage').style.display = 'none';
            document.getElementById('execution-stage').style.display = 'none';
            await updateStatus();
        } catch (e) {
            alert('Error: ' + e.message);
        }
    });
    
    document.getElementById('reset-button').addEventListener('click', async () => {
        try {
            await apiCall('/api/reset', 'POST');
            document.getElementById('text-input').value = '';
            document.getElementById('recording-status').textContent = '';
            document.getElementById('transcript-display').textContent = '';
            document.getElementById('intent-display').textContent = '';
            document.getElementById('plan-display').textContent = '';
            document.getElementById('execution-log').textContent = '';
            document.getElementById('answer-display').textContent = '';
            document.getElementById('transcription-stage').style.display = 'none';
            document.getElementById('intent-stage').style.display = 'none';
            document.getElementById('plan-stage').style.display = 'none';
            document.getElementById('execution-stage').style.display = 'none';
            document.getElementById('output-stage').style.display = 'none';
            document.getElementById('answer-stage').style.display = 'none';
            document.getElementById('ptt-button').classList.remove('recording');
            document.getElementById('ptt-cancel').style.display = 'none';
            await updateStatus();
        } catch (e) {
            alert('Error: ' + e.message);
        }
    });
    
    await updateStatus();
    setInterval(updateStatus, 2000);
});
