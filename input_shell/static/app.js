/**
 * ARGO Input Shell - Frontend Logic (v1.4.2)
 * 
 * RULE: Every action requires explicit confirmation
 * This script enforces the artifact chain: Transcription → Intent → Plan → Execution
 */

// State management
let appState = {
    transcript: null,
    intent: null,
    plan: null,
    mediaRecorder: null,
    audioChunks: [],
    isRecording: false,
};

// API helper
async function apiCall(endpoint, method = 'GET', body = null) {
    const options = {
        method: method,
        headers: { 'Content-Type': 'application/json' },
    };
    
    if (body) {
        options.body = JSON.stringify(body);
    }
    
    const response = await fetch(endpoint, options);
    if (!response.ok) {
        const error = await response.json();
        throw new Error(error.detail || 'API Error');
    }
    return await response.json();
}

// Update status display
async function updateStatus() {
    const status = await apiCall('/api/status');
    document.getElementById('session-info').innerHTML = `
        Session: ${status.session_id.substring(0, 8)}... | 
        Transcript: ${status.has_transcript ? '✓' : '✗'} | 
        Intent: ${status.has_intent ? '✓' : '✗'} | 
        Plan: ${status.has_plan ? '✓' : '✗'}
    `;
    
    // Update UI visibility
    document.getElementById('transcription-stage').style.display = 
        status.has_transcript ? 'block' : 'none';
    
    document.getElementById('intent-stage').style.display = 
        status.has_intent ? 'block' : 'none';
    
    document.getElementById('plan-stage').style.display = 
        status.has_plan ? 'block' : 'none';
    
    document.getElementById('execution-stage').style.display = 
        status.has_plan ? 'block' : 'none';
    
    // Update log
    if (status.execution_log.length > 0) {
        document.getElementById('output-stage').style.display = 'block';
        updateLog(status.execution_log);
    }
    
    return status;
}

// Update execution log
function updateLog(entries) {
    const logBox = document.getElementById('execution-log');
    logBox.innerHTML = '';
    
    entries.forEach(entry => {
        const logEntry = document.createElement('div');
        logEntry.className = 'log-entry';
        
        if (entry.action.includes('ERROR')) {
            logEntry.classList.add('error');
        } else if (entry.action.includes('SUCCESS')) {
            logEntry.classList.add('success');
        }
        
        const time = new Date(entry.timestamp).toLocaleTimeString();
        logEntry.textContent = `[${time}] ${entry.action}`;
        logBox.appendChild(logEntry);
    });
    
    // Auto-scroll to bottom
    logBox.scrollTop = logBox.scrollHeight;
}

// Format artifact for display
function formatArtifact(obj) {
    return JSON.stringify(obj, null, 2);
}

// ============================================================================
// TRANSCRIPTION HANDLING
// ============================================================================

// Push-to-Talk button
document.getElementById('ptt-button').addEventListener('click', async () => {
    const button = document.getElementById('ptt-button');
    const cancelBtn = document.getElementById('ptt-cancel');
    const statusDiv = document.getElementById('recording-status');
    
    if (appState.isRecording) {
        // Stop recording
        appState.mediaRecorder.stop();
        return;
    }
    
    // Start recording
    try {
        statusDiv.textContent = '🎤 Recording... (click to stop or use Cancel)';
        button.classList.add('recording');
        cancelBtn.style.display = 'inline-block';
        
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        appState.mediaRecorder = new MediaRecorder(stream);
        appState.audioChunks = [];
        appState.isRecording = true;
        
        appState.mediaRecorder.ondataavailable = (e) => {
            appState.audioChunks.push(e.data);
        };
        
        appState.mediaRecorder.onstop = async () => {
            appState.isRecording = false;
            button.classList.remove('recording');
            cancelBtn.style.display = 'none';
            statusDiv.textContent = 'Processing audio...';
            
            // Create blob
            const audioBlob = new Blob(appState.audioChunks, { type: 'audio/wav' });
            
            // Send to transcription endpoint
            const formData = new FormData();
            formData.append('file', audioBlob, 'recording.wav');
            
            try {
                const response = await fetch('/api/transcribe', {
                    method: 'POST',
                    body: formData,
                });
                
                if (!response.ok) {
                    const error = await response.json();
                    statusDiv.textContent = `❌ Error: ${error.detail}`;
                    return;
                }
                
                const result = await response.json();
                statusDiv.textContent = `✓ Transcribed: "${result.transcript}"`;
                
                // Update display
                document.getElementById('transcript-display').textContent = result.transcript;
                
                await updateStatus();
            } catch (e) {
                statusDiv.textContent = `❌ Error: ${e.message}`;
            }
        };
        
        appState.mediaRecorder.start();
    } catch (e) {
        statusDiv.textContent = `❌ Microphone error: ${e.message}`;
        button.classList.remove('recording');
    }
});

// Cancel recording button
document.getElementById('ptt-cancel').addEventListener('click', () => {
    if (appState.mediaRecorder && appState.isRecording) {
        appState.mediaRecorder.stop();
        const stream = appState.mediaRecorder.stream;
        stream.getTracks().forEach(track => track.stop());
        appState.isRecording = false;
        document.getElementById('recording-status').textContent = '✓ Recording cancelled';
        document.getElementById('ptt-button').classList.remove('recording');
        document.getElementById('ptt-cancel').style.display = 'none';
    }
});

// Text input handling (alternative to push-to-talk)
document.getElementById('text-input').addEventListener('keypress', async (e) => {
    if (e.key === 'Enter') {
        const text = e.target.value.trim();
        if (!text) return;
        
        // Simulate transcription
        document.getElementById('transcript-display').textContent = text;
        document.getElementById('recording-status').textContent = `✓ Text input: "${text}"`;
        
        // Clear input
        e.target.value = '';
        
        await updateStatus();
    }
});

// ============================================================================
// TRANSCRIPTION STAGE
// ============================================================================

document.getElementById('confirm-transcript').addEventListener('click', async () => {
    try {
        const result = await apiCall('/api/confirm-transcript', 'POST');
        
        // Display intent
        document.getElementById('intent-display').textContent = formatArtifact(result.intent);
        
        await updateStatus();
    } catch (e) {
        alert(`Error: ${e.message}`);
    }
});

document.getElementById('reject-transcript').addEventListener('click', async () => {
    try {
        await apiCall('/api/reject-transcript', 'POST');
        document.getElementById('transcript-display').textContent = '';
        document.getElementById('transcription-stage').style.display = 'none';
        
        await updateStatus();
    } catch (e) {
        alert(`Error: ${e.message}`);
    }
});

// ============================================================================
// INTENT STAGE
// ============================================================================

document.getElementById('confirm-intent').addEventListener('click', async () => {
    try {
        const result = await apiCall('/api/confirm-intent', 'POST');
        
        // Display plan
        document.getElementById('plan-display').textContent = formatArtifact(result.plan);
        
        await updateStatus();
    } catch (e) {
        alert(`Error: ${e.message}`);
    }
});

document.getElementById('reject-intent').addEventListener('click', async () => {
    try {
        await apiCall('/api/reject-intent', 'POST');
        document.getElementById('intent-display').textContent = '';
        document.getElementById('intent-stage').style.display = 'none';
        
        await updateStatus();
    } catch (e) {
        alert(`Error: ${e.message}`);
    }
});

// ============================================================================
// PLAN STAGE
// ============================================================================

// Confirm plan (just shows execution stage, no other processing)
// Button already wired to display execution stage via updateStatus()

document.getElementById('abort-plan').addEventListener('click', async () => {
    try {
        await apiCall('/api/abort-plan', 'POST');
        document.getElementById('plan-display').textContent = '';
        document.getElementById('plan-stage').style.display = 'none';
        document.getElementById('execution-stage').style.display = 'none';
        
        await updateStatus();
    } catch (e) {
        alert(`Error: ${e.message}`);
    }
});

// ============================================================================
// EXECUTION STAGE
// ============================================================================

document.getElementById('execute-button').addEventListener('click', async () => {
    try {
        const result = await apiCall('/api/execute', 'POST');
        
        // Display result
        if (result.result) {
            const logBox = document.getElementById('execution-log');
            const entry = document.createElement('div');
            entry.className = 'log-entry success';
            entry.textContent = `✓ Execution complete: ${result.result.execution_status}`;
            logBox.appendChild(entry);
        }
        
        await updateStatus();
    } catch (e) {
        alert(`Error: ${e.message}`);
    }
});

document.getElementById('abort-execute').addEventListener('click', async () => {
    try {
        await apiCall('/api/abort-plan', 'POST');
        document.getElementById('plan-display').textContent = '';
        document.getElementById('plan-stage').style.display = 'none';
        document.getElementById('execution-stage').style.display = 'none';
        
        await updateStatus();
    } catch (e) {
        alert(`Error: ${e.message}`);
    }
});

// ============================================================================
// RESET
// ============================================================================

document.getElementById('reset-button').addEventListener('click', async () => {
    try {
        await apiCall('/api/reset', 'POST');
        document.getElementById('text-input').value = '';
        document.getElementById('recording-status').textContent = '';
        document.getElementById('transcript-display').textContent = '';
        document.getElementById('intent-display').textContent = '';
        document.getElementById('plan-display').textContent = '';
        document.getElementById('execution-log').textContent = '';
        
        // Hide stages
        document.getElementById('transcription-stage').style.display = 'none';
        document.getElementById('intent-stage').style.display = 'none';
        document.getElementById('plan-stage').style.display = 'none';
        document.getElementById('execution-stage').style.display = 'none';
        document.getElementById('output-stage').style.display = 'none';
        
        await updateStatus();
    } catch (e) {
        alert(`Error: ${e.message}`);
    }
});

// ============================================================================
// INITIALIZATION
// ============================================================================

document.addEventListener('DOMContentLoaded', async () => {
    console.log('ARGO Input Shell v1.4.2 initialized');
    console.log('Rules: No background listening, all actions explicit confirmation');
    
    // Initial status update
    await updateStatus();
    
    // Periodic status updates
    setInterval(updateStatus, 2000);
});
