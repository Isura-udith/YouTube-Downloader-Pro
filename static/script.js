// State Management
let fetchedData = null;
let currentTab = 'downloader';
let activeDownloadsCount = 0;
let queuePollingInterval = null;
let suggestionsData = [];
let isLocal = true;         // initialized early; updated in initApp() from server config
let isFetching = false;     // debounce guard for fetch button
let historyCache = [];      // cached history items for reliable media playback

// DOM Elements
const urlInput = document.getElementById('url-input');
const fetchBtn = document.getElementById('fetch-btn');
const btnText = document.querySelector('.btn-text');
const spinner = document.querySelector('.spinner');
const clearBtn = document.getElementById('clear-btn');
const errorMessage = document.getElementById('error-message');
const ffmpegWarning = document.getElementById('ffmpeg-warning');

// Search Results elements
const searchResultsSection = document.getElementById('search-results-section');
const searchResultsGrid = document.getElementById('search-results-grid');
const closeSearchBtn = document.getElementById('close-search-btn');

// Suggestions elements
const suggestionsSection = document.getElementById('suggestions-section');
const suggestionsGrid = document.getElementById('suggestions-grid');
const suggestionTabBtns = document.querySelectorAll('.suggestion-tab-btn');

// Trim and Metadata elements
const trimToggleBtn = document.getElementById('trim-toggle-btn');
const trimInputsWrapper = document.getElementById('trim-inputs-wrapper');
const trimStart = document.getElementById('trim-start');
const trimEnd = document.getElementById('trim-end');
const metadataGroup = document.getElementById('metadata-group');
const metadataCheckbox = document.getElementById('metadata-checkbox');

// Media Player elements
const playerModal = document.getElementById('player-modal');
const playerTitle = document.getElementById('player-title');
const playerVideo = document.getElementById('player-video');
const playerAudio = document.getElementById('player-audio');
const playerCloseBtn = document.getElementById('player-close-btn');
const playerModalCloseX = document.getElementById('player-modal-close-x');

// Clear Action buttons
const clearQueueBtn = document.getElementById('clear-queue-btn');
const clearHistoryBtn = document.getElementById('clear-history-btn');

// System status — these elements may not exist in the HTML template.
// All usages are guarded with null checks so missing elements are harmless.
const statusDot = document.getElementById('status-dot');
const statusLabel = document.getElementById('status-label');
const ffmpegDot = document.getElementById('ffmpeg-dot');
const ffmpegLabel = document.getElementById('ffmpeg-label');

// Tab Panes
const tabPanes = document.querySelectorAll('.tab-pane');
const navBtns = document.querySelectorAll('.nav-btn');

// Settings Elements
const addLocationBtn = document.getElementById('add-location-btn');
const newLocationName = document.getElementById('new-location-name');
const newLocationPath = document.getElementById('new-location-path');
const settingsError = document.getElementById('settings-error');
const settingsSuccess = document.getElementById('settings-success');
const locationsListTbody = document.getElementById('locations-list-tbody');
const locationSelect = document.getElementById('location-select');
const playlistLocationSelect = document.getElementById('playlist-location-select');

let currentSettings = null;
const queueBadge = document.getElementById('queue-badge');

// Video details container elements
const videoInfo = document.getElementById('video-info');
const videoThumbnail = document.getElementById('video-thumbnail');
const videoTitle = document.getElementById('video-title');
const videoDuration = document.getElementById('video-duration');
const formatSelect = document.getElementById('format-select');
const resolutionGroup = document.getElementById('resolution-group');
const resolutionSelect = document.getElementById('resolution-select');
const bitrateGroup = document.getElementById('bitrate-group');
const bitrateSelect = document.getElementById('bitrate-select');
const subtitlesCheckbox = document.getElementById('subtitles-checkbox');
const downloadBtn = document.getElementById('download-btn');

// Playlist details container elements
const playlistInfo = document.getElementById('playlist-info');
const playlistTitle = document.getElementById('playlist-title');
const playlistCount = document.getElementById('playlist-count');
const playlistFormatSelect = document.getElementById('playlist-format-select');
const playlistResolutionGroup = document.getElementById('playlist-resolution-group');
const playlistResolutionSelect = document.getElementById('playlist-resolution-select');
const playlistBitrateGroup = document.getElementById('playlist-bitrate-group');
const playlistBitrateSelect = document.getElementById('playlist-bitrate-select');
const selectAllCheckbox = document.getElementById('select-all-checkbox');
const playlistDownloadBtn = document.getElementById('playlist-download-btn');
const selectedCountSpan = document.getElementById('selected-count');
const playlistEntriesList = document.getElementById('playlist-entries-list');

// Queue and History list containers
const queueList = document.getElementById('queue-list');
const historyList = document.getElementById('history-list');

// Combination Link Modal Elements
const linkModal = document.getElementById('link-modal');
const modalVideoBtn = document.getElementById('modal-video-btn');
const modalPlaylistBtn = document.getElementById('modal-playlist-btn');
const modalCancelBtn = document.getElementById('modal-cancel-btn');

// Base URL configuration (works dynamically for local & remote)
const API_BASE = window.location.origin + '/api';

// Get or generate unique client session ID
let clientId = localStorage.getItem('yt_downloader_client_id');
if (!clientId) {
    clientId = 'client_' + Math.random().toString(36).substring(2, 15) + Math.random().toString(36).substring(2, 15);
    localStorage.setItem('yt_downloader_client_id', clientId);
}

// Helper fetch wrapper to inject X-Client-ID header
async function apiFetch(url, options = {}) {
    options.headers = options.headers || {};
    options.headers['X-Client-ID'] = clientId;
    return fetch(url, options);
}

// Format time utility
function formatSeconds(seconds) {
    if (!seconds) return '0:00';
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = Math.floor(seconds % 60);
    if (h > 0) return `${h}:${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
    return `${m}:${s.toString().padStart(2, '0')}`;
}

// Format timestamp utility (relative time)
function formatTimeAgo(isoString) {
    if (!isoString) return '';
    const date = new Date(isoString);
    const now = new Date();
    const diffMs = now - date;
    const diffMins = Math.floor(diffMs / 60000);
    const diffHours = Math.floor(diffMins / 60);
    
    if (diffMins < 1) return 'Just now';
    if (diffMins < 60) return `${diffMins}m ago`;
    if (diffHours < 24) return `${diffHours}h ago`;
    return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}

// Client-side time parser (matches backend parse_time_to_seconds)
function parseTimeToSecondsClient(timeStr) {
    if (timeStr === null || timeStr === undefined) return null;
    if (typeof timeStr === 'number') return isNaN(timeStr) ? null : timeStr;
    timeStr = String(timeStr).trim();
    if (!timeStr) return null;

    if (timeStr.includes('.') && !timeStr.includes(':')) {
        const parts = timeStr.split('.');
        if (parts.length > 2 || (parts.length === 2 && parts[1].length === 2)) {
            timeStr = timeStr.replace(/\./g, ':');
        }
    }

    if (!timeStr.includes(':')) {
        const val = parseFloat(timeStr);
        return isNaN(val) ? null : val;
    }

    const parts = timeStr.split(':');
    if (parts.some(p => isNaN(Number(p)))) return null;
    if (parts.length === 2) {
        return parseInt(parts[0], 10) * 60 + parseFloat(parts[1]);
    } else if (parts.length === 3) {
        return parseInt(parts[0], 10) * 3600 + parseInt(parts[1], 10) * 60 + parseFloat(parts[2]);
    }
    return null;
}

// Toast notification helper
function showToast(message, type = 'info') {
    let container = document.getElementById('toast-container');
    if (!container) {
        container = document.createElement('div');
        container.id = 'toast-container';
        container.className = 'toast-container';
        document.body.appendChild(container);
    }
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.textContent = message;
    container.appendChild(toast);
    setTimeout(() => {
        toast.classList.add('fade-out');
        setTimeout(() => toast.remove(), 300);
    }, 3200);
}

// Clear URL input field
clearBtn.addEventListener('click', () => {
    urlInput.value = '';
    clearBtn.classList.add('hidden');
    
    // Hide downloader result views
    if (videoInfo) videoInfo.classList.add('hidden');
    if (playlistInfo) playlistInfo.classList.add('hidden');
    if (searchResultsSection) searchResultsSection.classList.add('hidden');
    if (errorMessage) errorMessage.classList.add('hidden');
    
    // Restore suggestions view
    if (suggestionsSection) suggestionsSection.classList.remove('hidden');
    
    urlInput.focus();
});

urlInput.addEventListener('input', () => {
    if (urlInput.value.trim().length > 0) {
        clearBtn.classList.remove('hidden');
    } else {
        clearBtn.classList.add('hidden');
    }
});

// Reset/Go to Home page (Downloader tab)
function goHome() {
    urlInput.value = '';
    clearBtn.classList.add('hidden');
    
    // Hide downloader result views
    if (videoInfo) videoInfo.classList.add('hidden');
    if (playlistInfo) playlistInfo.classList.add('hidden');
    if (searchResultsSection) searchResultsSection.classList.add('hidden');
    if (errorMessage) errorMessage.classList.add('hidden');
    
    // Restore suggestions view
    if (suggestionsSection) suggestionsSection.classList.remove('hidden');
    
    switchTab('downloader');
}

// Logo brand click navigation
const logoBrand = document.querySelector('.logo-brand');
if (logoBrand) {
    logoBrand.addEventListener('click', goHome);
}

// Tab navigation handler
function switchTab(tabId) {
    if (!tabId) return;
    currentTab = tabId;
    
    // Toggle nav active state
    navBtns.forEach(btn => {
        if (btn.getAttribute('data-tab') === tabId) {
            btn.classList.add('active');
        } else {
            btn.classList.remove('active');
        }
    });

    // Toggle tab panes active state
    tabPanes.forEach(pane => {
        if (pane.id === `${tabId}-tab`) {
            pane.classList.add('active');
        } else {
            pane.classList.remove('active');
        }
    });

    // Trigger tab-specific actions
    if (tabId === 'history') {
        loadHistory();
    } else if (tabId === 'settings') {
        loadSettings();
    }
}

navBtns.forEach(btn => {
    btn.addEventListener('click', () => {
        const tab = btn.getAttribute('data-tab');
        if (tab) {
            if (tab === 'downloader') {
                goHome();
            } else {
                switchTab(tab);
            }
        }
    });
});

// Set loading state on main fetch button
function setLoading(isLoading) {
    if (isLoading) {
        btnText.classList.add('hidden');
        spinner.classList.remove('hidden');
        fetchBtn.disabled = true;
        urlInput.disabled = true;
    } else {
        btnText.classList.remove('hidden');
        spinner.classList.add('hidden');
        fetchBtn.disabled = false;
        urlInput.disabled = false;
    }
}

function isYoutubeUrl(url) {
    return url.includes('youtube.com/') || url.includes('youtu.be/') || url.includes('www.youtube.com/') || url.includes('m.youtube.com/') || url.includes('music.youtube.com/');
}

// Fetch Video/Playlist Information
fetchBtn.addEventListener('click', async () => {
    const url = urlInput.value.trim();
    if (!url) return;
    if (isFetching) return; // debounce
    isFetching = true;

    setLoading(true);
    errorMessage.classList.add('hidden');
    ffmpegWarning.classList.add('hidden');
    videoInfo.classList.add('hidden');
    playlistInfo.classList.add('hidden');
    if (searchResultsSection) searchResultsSection.classList.add('hidden');
    if (suggestionsSection) suggestionsSection.classList.add('hidden');

    // Handle search query
    if (!isYoutubeUrl(url)) {
        try {
            const response = await apiFetch(`${API_BASE}/search`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ query: url })
            });
            const data = await response.json();
            if (!response.ok) throw new Error(data.error || 'Failed to search YouTube');
            renderSearchResults(data.results);
        } catch (error) {
            errorMessage.textContent = error.message;
            errorMessage.classList.remove('hidden');
        } finally {
            setLoading(false);
            isFetching = false;
        }
        return;
    }

    try {
        const response = await apiFetch(`${API_BASE}/info`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url })
        });

        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.error || 'Failed to retrieve video details');
        }

        fetchedData = data;

        // Update system FFmpeg status display
        updateFFmpegStatus(data.has_ffmpeg);

        // Check if combination link (video inside a playlist)
        if (data.type === 'video' && data.associated_playlist) {
            // Show combination prompt modal
            linkModal.classList.remove('hidden');
        } else if (data.type === 'playlist') {
            loadPlaylistView(data);
        } else {
            loadVideoView(data);
        }

    } catch (error) {
        errorMessage.textContent = error.message;
        errorMessage.classList.remove('hidden');
    } finally {
        setLoading(false);
        isFetching = false;
    }
});

// Enter key triggers fetch
urlInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
        e.preventDefault();
        fetchBtn.click();
    }
});

// Modal Dialog Button Actions
modalVideoBtn.addEventListener('click', () => {
    linkModal.classList.add('hidden');
    if (fetchedData) loadVideoView(fetchedData);
});

modalPlaylistBtn.addEventListener('click', async () => {
    linkModal.classList.add('hidden');
    const playlistId = fetchedData.associated_playlist;
    if (!playlistId) return;
    
    // Fetch playlist details explicitly
    setLoading(true);
    try {
        const url = `https://www.youtube.com/playlist?list=${playlistId}`;
        const response = await apiFetch(`${API_BASE}/info`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url })
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || 'Failed to load playlist');
        
        fetchedData = data;
        loadPlaylistView(data);
    } catch (error) {
        errorMessage.textContent = error.message;
        errorMessage.classList.remove('hidden');
    } finally {
        setLoading(false);
    }
});

modalCancelBtn.addEventListener('click', () => {
    linkModal.classList.add('hidden');
});

// Populate and display single video options card
function loadVideoView(data) {
    videoTitle.textContent = data.title;
    videoThumbnail.src = data.thumbnail || '/static/logo-placeholder.png';
    videoThumbnail.onerror = () => {
        videoThumbnail.onerror = null;
        videoThumbnail.src = '/static/logo-placeholder.png';
    };
    videoDuration.textContent = formatSeconds(data.duration);

    // Populate video resolutions list
    resolutionSelect.innerHTML = '';
    if (data.resolutions && data.resolutions.length > 0) {
        data.resolutions.forEach(res => {
            const opt = document.createElement('option');
            opt.value = res;
            opt.textContent = `${res}p`;
            resolutionSelect.appendChild(opt);
        });
    } else {
        const opt = document.createElement('option');
        opt.value = '720';
        opt.textContent = '720p (Default)';
        resolutionSelect.appendChild(opt);
    }

    // Toggle display formatting dropdowns
    formatSelect.value = 'mp4';
    resolutionGroup.classList.remove('hidden');
    bitrateGroup.classList.add('hidden');
    if (metadataGroup) metadataGroup.classList.add('hidden');
    subtitlesCheckbox.checked = false;

    // Reset trim fields
    if (trimToggleBtn) {
        trimToggleBtn.classList.remove('open');
        trimInputsWrapper.classList.add('hidden');
        trimStart.value = '';
        trimEnd.value = '';
    }

    videoInfo.classList.remove('hidden');
}

// Toggle format quality fields in video card
formatSelect.addEventListener('change', (e) => {
    if (e.target.value === 'mp3') {
        resolutionGroup.classList.add('hidden');
        bitrateGroup.classList.remove('hidden');
        if (metadataGroup) metadataGroup.classList.remove('hidden');
    } else {
        resolutionGroup.classList.remove('hidden');
        bitrateGroup.classList.add('hidden');
        if (metadataGroup) metadataGroup.classList.add('hidden');
    }
});

// Download Video trigger
downloadBtn.addEventListener('click', async () => {
    if (!fetchedData) return;

    const type = formatSelect.value;
    const resolution = resolutionSelect.value;
    const bitrate = bitrateSelect.value;
    const subtitles = subtitlesCheckbox.checked;
    const location_id = locationSelect ? locationSelect.value : null;
    const embed_metadata = metadataCheckbox ? metadataCheckbox.checked : false;
    const start_time = trimStart ? trimStart.value.trim() : '';
    const end_time = trimEnd ? trimEnd.value.trim() : '';

    if (start_time !== '' || end_time !== '') {
        const sSec = parseTimeToSecondsClient(start_time);
        const eSec = parseTimeToSecondsClient(end_time);
        if (start_time !== '' && sSec === null) {
            alert('Invalid Start Time format. Use MM:SS or seconds (e.g. 00:30)');
            return;
        }
        if (end_time !== '' && eSec === null) {
            alert('Invalid End Time format. Use MM:SS or seconds (e.g. 02:15)');
            return;
        }
        if (sSec !== null && sSec < 0) {
            alert('Start Time cannot be negative.');
            return;
        }
        if (eSec !== null && eSec <= 0) {
            alert('End Time must be greater than zero.');
            return;
        }
        if (sSec !== null && eSec !== null && sSec >= eSec) {
            alert('Start Time must be earlier than End Time.');
            return;
        }
    }

    const payload = {
        url: `https://www.youtube.com/watch?v=${fetchedData.video_id}`,
        type,
        resolution,
        bitrate,
        subtitles,
        location_id,
        title: fetchedData.title,
        thumbnail: fetchedData.thumbnail,
        duration: fetchedData.duration,
        start_time,
        end_time,
        embed_metadata
    };

    try {
        const response = await apiFetch(`${API_BASE}/download`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });

        const data = await response.json();
        if (!response.ok) throw new Error(data.error || 'Failed to add to download queue');

        showToast(`Added "${fetchedData.title}" to download queue`, 'success');

        // Switch to queue tab to let them see progress
        switchTab('queue');
        pollQueueStatus(); // force poll queue
        
    } catch (error) {
        alert(`Error: ${error.message}`);
    }
});

// Populate and display playlist entries card
function loadPlaylistView(data) {
    playlistTitle.textContent = data.title;
    playlistCount.textContent = `${data.entries.length} Videos`;

    playlistEntriesList.innerHTML = '';
    data.entries.forEach(entry => {
        const row = document.createElement('div');
        row.className = 'playlist-entry-row';
        row.innerHTML = `
            <label class="checkbox-container">
                <input type="checkbox" class="entry-checkbox" data-id="${escapeHtml(entry.id)}" data-title="${escapeHtml(entry.title)}" data-thumb="${escapeHtml(entry.thumbnail || '')}" data-duration="${entry.duration || 0}" checked>
                <span class="checkmark"></span>
            </label>
            <img class="playlist-entry-thumbnail" src="${escapeHtml(entry.thumbnail || '/static/logo-placeholder.png')}" alt="" onerror="this.onerror=null;this.src='/static/logo-placeholder.png';">
            <span class="playlist-entry-title" title="${escapeHtml(entry.title)}">${escapeHtml(entry.title)}</span>
            <span class="playlist-entry-duration">${formatSeconds(entry.duration)}</span>
        `;
        playlistEntriesList.appendChild(row);
    });

    // Reset formats
    playlistFormatSelect.value = 'mp4';
    playlistResolutionGroup.classList.remove('hidden');
    playlistBitrateGroup.classList.add('hidden');
    selectAllCheckbox.checked = true;

    // Listeners for checkbox counting
    const checkboxes = document.querySelectorAll('.entry-checkbox');
    checkboxes.forEach(cb => {
        cb.addEventListener('change', updateSelectedPlaylistCount);
    });
    updateSelectedPlaylistCount();

    playlistInfo.classList.remove('hidden');
}

// Toggle format quality fields in playlist card
playlistFormatSelect.addEventListener('change', (e) => {
    if (e.target.value === 'mp3') {
        playlistResolutionGroup.classList.add('hidden');
        playlistBitrateGroup.classList.remove('hidden');
    } else {
        playlistResolutionGroup.classList.remove('hidden');
        playlistBitrateGroup.classList.add('hidden');
    }
});

// Check/Uncheck all playlist entries
selectAllCheckbox.addEventListener('change', (e) => {
    const checkboxes = document.querySelectorAll('.entry-checkbox');
    checkboxes.forEach(cb => {
        cb.checked = e.target.checked;
    });
    updateSelectedPlaylistCount();
});

function updateSelectedPlaylistCount() {
    const selected = document.querySelectorAll('.entry-checkbox:checked').length;
    selectedCountSpan.textContent = selected;
    playlistDownloadBtn.disabled = selected === 0;
}

// Download selected items from playlist bulk list
playlistDownloadBtn.addEventListener('click', async () => {
    const selectedCheckboxes = document.querySelectorAll('.entry-checkbox:checked');
    if (selectedCheckboxes.length === 0) return;

    const format = playlistFormatSelect.value;
    const resolution = playlistResolutionSelect.value;
    const bitrate = playlistBitrateSelect.value;
    const location_id = playlistLocationSelect ? playlistLocationSelect.value : null;

    playlistDownloadBtn.disabled = true;
    playlistDownloadBtn.textContent = 'Adding...';

    // Call API for each selected item
    for (let cb of selectedCheckboxes) {
        const videoId = cb.getAttribute('data-id');
        const title = cb.getAttribute('data-title');
        const thumbnail = cb.getAttribute('data-thumb');
        const duration = parseInt(cb.getAttribute('data-duration')) || 0;

        const payload = {
            url: `https://www.youtube.com/watch?v=${videoId}`,
            type: format,
            resolution,
            bitrate,
            subtitles: false,
            location_id,
            title,
            thumbnail,
            duration
        };

        try {
            await apiFetch(`${API_BASE}/download`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
        } catch (error) {
            console.error('Failed to queue playlist item', videoId, error);
        }
    }

    playlistDownloadBtn.disabled = false;
    playlistDownloadBtn.textContent = `Download Selected (${selectedCheckboxes.length})`;

    // Switch to queue
    switchTab('queue');
    pollQueueStatus();
});

// Update system statuses UI
function updateFFmpegStatus(hasFFmpeg) {
    if (hasFFmpeg) {
        if (ffmpegDot) ffmpegDot.className = 'status-dot green';
        if (ffmpegLabel) ffmpegLabel.textContent = 'FFmpeg Enabled';
        if (ffmpegWarning) ffmpegWarning.classList.add('hidden');
    } else {
        if (ffmpegDot) ffmpegDot.className = 'status-dot orange';
        if (ffmpegLabel) ffmpegLabel.textContent = 'FFmpeg Missing';
        if (ffmpegWarning) ffmpegWarning.classList.remove('hidden');
    }
}

// Fetch Active Queue from backend
async function pollQueueStatus() {
    try {
        const response = await apiFetch(`${API_BASE}/active`);
        const data = await response.json();

        renderQueueList(data);
    } catch (error) {
        console.error('Error fetching queue status:', error);
        if (statusDot) statusDot.className = 'status-dot red';
        if (statusLabel) statusLabel.textContent = 'Disconnected';
    }
}

// Render the Active Queue tab list (declared as var so it can be wrapped by adaptive polling)
var renderQueueList = function(activeDownloads) {
    const ids = Object.keys(activeDownloads);
    
    // Filter active items for badges
    const runningDownloads = ids.filter(id => 
        ['downloading', 'queued', 'aborting'].includes(activeDownloads[id].status)
    );
    
    activeDownloadsCount = runningDownloads.length;

    // Update Sidebar queue badge
    if (activeDownloadsCount > 0) {
        queueBadge.textContent = activeDownloadsCount;
        queueBadge.classList.remove('hidden');
    } else {
        queueBadge.classList.add('hidden');
    }

    if (ids.length === 0) {
        queueList.innerHTML = `
            <div class="empty-state">
                <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="7 10 12 15 17 10"></polyline><line x1="12" y1="15" x2="12" y2="3"></line></svg>
                <p>No downloads in progress or history.</p>
                <button class="empty-btn" onclick="switchTab('downloader')">Start a Download</button>
            </div>
        `;
        return;
    }

    // Sort queue: running items first, then errors/completed
    const sortedIds = ids.sort((a, b) => {
        const statusOrder = { 'downloading': 1, 'queued': 2, 'aborting': 3, 'completed': 4, 'error': 5, 'aborted': 6 };
        return (statusOrder[activeDownloads[a].status] || 9) - (statusOrder[activeDownloads[b].status] || 9);
    });

    let html = '';
    sortedIds.forEach(id => {
        const dl = activeDownloads[id];
        let statusText = dl.status_text || 'Processing...';
        let statusColor = 'var(--text-main)';
        let speedDisplay = '';
        const progressVal = Number(dl.progress) || 0;
        let progressBarWidth = progressVal;
        let isRunning = ['downloading', 'queued', 'aborting'].includes(dl.status);

        if (dl.status === 'downloading') {
            statusText = dl.status_text || `Downloading... ${progressVal.toFixed(1)}%`;
            speedDisplay = `Speed: <strong>${escapeHtml(dl.speed || 'N/A')}</strong> &bull; ETA: <strong>${escapeHtml(dl.eta || 'N/A')}</strong>`;
        } else if (dl.status === 'queued') {
            statusText = 'Waiting in queue...';
        } else if (dl.status === 'aborting') {
            statusText = 'Aborting...';
            statusColor = 'var(--warning)';
        } else if (dl.status === 'completed') {
            statusText = dl.status_text || 'Finished successfully';
            statusColor = 'var(--success)';
            progressBarWidth = 100;
        } else if (dl.status === 'error') {
            statusText = `Error: ${dl.error || 'Failed'}`;
            statusColor = 'var(--danger)';
        } else if (dl.status === 'aborted') {
            statusText = 'Download Aborted';
            statusColor = 'var(--text-muted)';
        }

        html += `
            <div class="queue-item" id="queue-item-${id}">
                <img class="queue-thumbnail" src="${escapeHtml(dl.thumbnail || '/static/logo-placeholder.png')}" alt="" onerror="this.onerror=null;this.src='/static/logo-placeholder.png';">
                <div class="queue-details">
                    <div style="display: flex; justify-content: space-between; align-items: center;">
                        <span class="queue-title" title="${escapeHtml(dl.title)}">${escapeHtml(dl.title)}</span>
                        <span class="format-pill ${dl.format}">${dl.format.toUpperCase()} ${dl.resolution ? dl.resolution + 'p' : ''}</span>
                    </div>
                    <div class="queue-meta">
                        <span style="color: ${statusColor}; font-weight: 700;">${escapeHtml(statusText)}</span>
                        ${isRunning ? `<span>Size: <strong>${escapeHtml(dl.filesize || 'Unknown')}</strong></span>` : ''}
                        ${speedDisplay ? `<span>${speedDisplay}</span>` : ''}
                    </div>
                    <div class="queue-progress-bar">
                        <div class="queue-progress-fill" style="width: ${progressBarWidth}%; ${dl.status === 'error' ? 'background: var(--danger);' : ''}"></div>
                    </div>
                </div>
                ${isRunning ? `
                    <div class="queue-action">
                        <button class="abort-btn" onclick="abortDownload('${id}')" title="Cancel Download">&times;</button>
                    </div>
                ` : ''}
            </div>
        `;
    });

    queueList.innerHTML = html;
};

// Abort active task
async function abortDownload(downloadId) {
    try {
        const response = await apiFetch(`${API_BASE}/abort/${downloadId}`, { method: 'POST' });
        if (response.ok) {
            showToast('Download aborted', 'info');
            pollQueueStatus();
        }
    } catch (error) {
        console.error('Failed to abort download', error);
    }
}

// Load and Render Completed History
async function loadHistory() {
    try {
        const response = await apiFetch(`${API_BASE}/history`);
        const data = await response.json();
        renderHistoryList(data);
    } catch (error) {
        console.error('Error fetching history:', error);
    }
}

function renderHistoryList(historyItems) {
    historyCache = Array.isArray(historyItems) ? historyItems : [];

    if (historyCache.length === 0) {
        historyList.innerHTML = `
            <div class="empty-state">
                <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M12 22c5.523 0 10-4.477 10-10S17.523 2 12 2 2 6.477 2 12s4.477 10 10 10z"/><path d="M9 12l2 2 4-4"/></svg>
                <p>No completed downloads yet.</p>
            </div>
        `;
        return;
    }

    let html = '';
    historyCache.forEach(item => {
        const downloadUrl = `${API_BASE}/files/by-id/${encodeURIComponent(item.download_id)}?download=true`;
        const details = item.format === 'mp4' 
            ? `${item.resolution || '720'}p` 
            : `${item.bitrate || '192'}kbps`;
        const fileExists = item.file_exists !== false;
        
        html += `
            <div class="history-item" id="history-item-${item.download_id}">
                <img class="queue-thumbnail" src="${escapeHtml(item.thumbnail || '/static/logo-placeholder.png')}" alt="" onerror="this.onerror=null;this.src='/static/logo-placeholder.png';">
                <div class="history-details">
                    <span class="history-title" title="${escapeHtml(item.title)}">${escapeHtml(item.title)}</span>
                    <div class="history-meta">
                        <span class="format-pill ${item.format}">${item.format.toUpperCase()}</span>
                        <span>Quality: <strong>${details}</strong></span>
                        <span>Size: <strong>${escapeHtml(item.filesize || 'N/A')}</strong></span>
                        <span>Saved: <strong>${formatTimeAgo(item.timestamp)}</strong></span>
                        ${!fileExists ? `<span class="missing-badge" title="File was moved or deleted from disk">Missing from disk</span>` : ''}
                    </div>
                </div>
                <div class="history-actions">
                    ${isLocal ? `
                    <button class="action-btn locate-btn ${!fileExists ? 'disabled' : ''}" ${!fileExists ? 'disabled' : ''} onclick="openFileFolder('${item.download_id}')" title="${fileExists ? 'Show in File Explorer' : 'File missing from disk'}" style="background: rgba(59, 130, 246, 0.12); color: #60a5fa; border: 1px solid rgba(59, 130, 246, 0.25); display: flex; align-items: center; gap: 4px;">
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="opacity: 1; color: #60a5fa; margin: 0;"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>
                        Locate
                    </button>
                    ` : ''}
                    <button class="action-btn play-btn ${!fileExists ? 'disabled' : ''}" ${!fileExists ? 'disabled' : ''} onclick="playMediaById('${item.download_id}')" title="${fileExists ? 'Play media in browser' : 'File missing from disk'}">
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polygon points="5 3 19 12 5 21 5 3"/></svg>
                        Play
                    </button>
                    <a href="${downloadUrl}" class="action-btn dl ${!fileExists ? 'disabled' : ''}" ${!fileExists ? 'tabindex="-1"' : 'download'} title="${fileExists ? 'Download to local drive' : 'File missing from disk'}">
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
                        Download
                    </a>
                    <button class="action-btn del" onclick="deleteHistoryItem('${item.download_id}')" title="Delete record and file">
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/><line x1="10" y1="11" x2="10" y2="17"/><line x1="14" y1="11" x2="14" y2="17"/></svg>
                        Delete
                    </button>
                </div>
            </div>
        `;
    });

    historyList.innerHTML = html;
}

// Delete history item
// Open file folder (Local mode only)
async function openFileFolder(downloadId) {
    try {
        const response = await apiFetch(`${API_BASE}/open-folder`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ download_id: downloadId })
        });
        if (!response.ok) {
            const data = await response.json();
            alert(`Error: ${data.error}`);
        }
    } catch (error) {
        console.error('Failed to open file folder:', error);
    }
}

async function deleteHistoryItem(downloadId) {
    if (!confirm('Are you sure you want to delete this completed file from the server?')) return;
    
    try {
        const response = await apiFetch(`${API_BASE}/history/${downloadId}`, { method: 'DELETE' });
        if (response.ok) {
            loadHistory();
        }
    } catch (error) {
        console.error('Failed to delete history item', error);
    }
}

// Settings Management Functions
async function loadSettings() {
    try {
        const response = await apiFetch(`${API_BASE}/settings`);
        const data = await response.json();
        currentSettings = data;
        
        renderLocationsList(data.locations);
        updateLocationsDropdowns(data.locations);
    } catch (error) {
        console.error('Failed to load settings:', error);
    }
}

function renderLocationsList(locations) {
    if (!locationsListTbody) return;
    locationsListTbody.innerHTML = '';
    
    locations.forEach(loc => {
        const tr = document.createElement('tr');
        
        const isDefault = loc.is_default;
        const statusText = isDefault ? '<span class="status-pill active">Active Default</span>' : '<span class="status-pill">Inactive</span>';
        
        let actionButtons = '';
        if (!isDefault) {
            actionButtons += `
                <button class="settings-action-btn active-btn" onclick="setActiveLocation('${loc.id}')">Make Default</button>
            `;
        }
        if (loc.id !== 'default') {
            actionButtons += `
                <button class="settings-action-btn delete-btn" onclick="deleteLocation('${loc.id}')">Remove</button>
            `;
        }
        
        tr.innerHTML = `
            <td class="location-name-cell">${escapeHtml(loc.name)}</td>
            <td class="location-path-cell"><code>${escapeHtml(loc.path)}</code></td>
            <td>${statusText}</td>
            <td>${actionButtons || '<span class="system-default-label">System default</span>'}</td>
        `;
        locationsListTbody.appendChild(tr);
    });
}

function updateLocationsDropdowns(locations) {
    if (!locationSelect || !playlistLocationSelect) return;
    
    const optionsHtml = locations.map(loc => {
        const suffix = loc.is_default ? ' (Default)' : '';
        return `<option value="${loc.id}" ${loc.is_default ? 'selected' : ''}>${escapeHtml(loc.name)}${suffix}</option>`;
    }).join('');
    
    locationSelect.innerHTML = optionsHtml;
    playlistLocationSelect.innerHTML = optionsHtml;
}

async function setActiveLocation(id) {
    try {
        const response = await apiFetch(`${API_BASE}/settings/location/active`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ id })
        });
        if (response.ok) {
            loadSettings();
        } else {
            const data = await response.json();
            alert(`Error: ${data.error}`);
        }
    } catch (error) {
        console.error('Failed to set active location:', error);
    }
}

async function deleteLocation(id) {
    if (!confirm('Are you sure you want to remove this download location?')) return;
    try {
        const response = await apiFetch(`${API_BASE}/settings/location/${id}`, {
            method: 'DELETE'
        });
        if (response.ok) {
            loadSettings();
        } else {
            const data = await response.json();
            alert(`Error: ${data.error}`);
        }
    } catch (error) {
        console.error('Failed to delete location:', error);
    }
}

// Hook up Add Location button listener
document.addEventListener('DOMContentLoaded', () => {
    if (addLocationBtn) {
        addLocationBtn.addEventListener('click', async () => {
            const name = newLocationName.value.trim();
            const path = newLocationPath.value.trim();
            
            settingsError.classList.add('hidden');
            settingsSuccess.classList.add('hidden');
            
            if (!name || !path) {
                settingsError.textContent = 'Both Name and Folder Path are required.';
                settingsError.classList.remove('hidden');
                return;
            }
            
            try {
                addLocationBtn.disabled = true;
                const response = await apiFetch(`${API_BASE}/settings/location`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ name, path })
                });
                const data = await response.json();
                if (response.ok) {
                    settingsSuccess.classList.remove('hidden');
                    newLocationName.value = '';
                    newLocationPath.value = '';
                    loadSettings();
                } else {
                    settingsError.textContent = data.error || 'Failed to add location.';
                    settingsError.classList.remove('hidden');
                }
            } catch (error) {
                settingsError.textContent = error.message;
                settingsError.classList.remove('hidden');
            } finally {
                addLocationBtn.disabled = false;
            }
        });
    }
});

// Helper to escape HTML tags
function escapeHtml(text) {
    if (!text) return '';
    const map = {
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#039;'
    };
    return text.replace(/[&<>"']/g, function(m) { return map[m]; });
}

// Search rendering
function renderSearchResults(results) {
    if (!searchResultsGrid || !searchResultsSection) return;
    searchResultsGrid.innerHTML = '';
    searchResultsSection.classList.remove('hidden');
    videoInfo.classList.add('hidden');
    playlistInfo.classList.add('hidden');
    
    if (results.length === 0) {
        searchResultsGrid.innerHTML = '<p class="empty-search" style="grid-column: 1/-1; text-align: center; color: var(--text-muted); padding: 2rem 0;">No results found.</p>';
        return;
    }
    
    results.forEach(item => {
        const card = document.createElement('div');
        card.className = 'search-result-card';
        card.innerHTML = `
            <div class="search-result-thumb-container">
                <img class="search-result-thumb" src="${escapeHtml(item.thumbnail || '/static/logo-placeholder.png')}" alt="Thumbnail" onerror="this.onerror=null;this.src='/static/logo-placeholder.png';">
                <span class="search-result-duration">${formatSeconds(item.duration)}</span>
            </div>
            <div class="search-result-info">
                <span class="search-result-title" title="${escapeHtml(item.title)}">${escapeHtml(item.title)}</span>
                <span class="search-result-channel">${escapeHtml(item.uploader)}</span>
            </div>
        `;
        card.addEventListener('click', () => {
            urlInput.value = item.url;
            clearBtn.classList.remove('hidden');
            searchResultsSection.classList.add('hidden');
            fetchBtn.click();
        });
        searchResultsGrid.appendChild(card);
    });
    
    searchResultsSection.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

// Media player handlers
function playMediaById(downloadId) {
    if (!playerModal || !playerTitle || !playerVideo || !playerAudio) return;
    const item = historyCache.find(h => h.download_id === downloadId);
    if (!item) return;

    if (item.file_exists === false) {
        showToast('This file is no longer available on disk.', 'error');
        return;
    }

    const fileUrl = `${API_BASE}/files/by-id/${encodeURIComponent(downloadId)}`;
    playerTitle.textContent = item.title;
    
    playerVideo.classList.add('hidden');
    playerAudio.classList.add('hidden');
    playerVideo.src = '';
    playerAudio.src = '';
    
    if (item.format === 'mp3') {
        playerAudio.src = fileUrl;
        playerAudio.classList.remove('hidden');
        playerAudio.load();
        playerAudio.play().catch(e => console.log('Audio autoplay blocked', e));
    } else {
        playerVideo.src = fileUrl;
        playerVideo.classList.remove('hidden');
        playerVideo.load();
        playerVideo.play().catch(e => console.log('Video autoplay blocked', e));
    }
    
    playerModal.classList.remove('hidden');
}

function playMedia(filename, title, format) {
    if (!playerModal || !playerTitle || !playerVideo || !playerAudio) return;
    
    const decodedFilename = decodeURIComponent(filename);
    const fileUrl = `${API_BASE}/files/${encodeURIComponent(decodedFilename)}`;
    playerTitle.textContent = title;
    
    playerVideo.classList.add('hidden');
    playerAudio.classList.add('hidden');
    playerVideo.src = '';
    playerAudio.src = '';
    
    if (format === 'mp3') {
        playerAudio.src = fileUrl;
        playerAudio.classList.remove('hidden');
        playerAudio.load();
        playerAudio.play().catch(e => console.log('Audio autoplay blocked', e));
    } else {
        playerVideo.src = fileUrl;
        playerVideo.classList.remove('hidden');
        playerVideo.load();
        playerVideo.play().catch(e => console.log('Video autoplay blocked', e));
    }
    
    playerModal.classList.remove('hidden');
}

function stopMedia() {
    if (playerVideo) playerVideo.pause();
    if (playerAudio) playerAudio.pause();
    if (playerVideo) playerVideo.src = '';
    if (playerAudio) playerAudio.src = '';
    if (playerModal) playerModal.classList.add('hidden');
}

// Load and Render Suggestions/Recommendations
async function loadSuggestions(force = false) {
    try {
        // Show skeleton loading animations while refreshing
        if (suggestionsGrid) {
            suggestionsGrid.innerHTML = `
                <div class="skeleton-card">
                    <div class="skeleton-thumb"></div>
                    <div class="skeleton-title"></div>
                    <div class="skeleton-uploader"></div>
                </div>
                <div class="skeleton-card">
                    <div class="skeleton-thumb"></div>
                    <div class="skeleton-title"></div>
                    <div class="skeleton-uploader"></div>
                </div>
                <div class="skeleton-card">
                    <div class="skeleton-thumb"></div>
                    <div class="skeleton-title"></div>
                    <div class="skeleton-uploader"></div>
                </div>
                <div class="skeleton-card">
                    <div class="skeleton-thumb"></div>
                    <div class="skeleton-title"></div>
                    <div class="skeleton-uploader"></div>
                </div>
            `;
        }

        const url = force ? `${API_BASE}/suggestions?force=true` : `${API_BASE}/suggestions`;
        const response = await apiFetch(url);
        if (!response.ok) throw new Error('Failed to fetch suggestions');
        const data = await response.json();
        suggestionsData = data;
        
        // Find which category tab is active
        let activeCategory = 'all';
        if (suggestionTabBtns) {
            suggestionTabBtns.forEach(btn => {
                if (btn.classList.contains('active')) {
                    activeCategory = btn.getAttribute('data-category') || 'all';
                }
            });
        }
        renderSuggestions(activeCategory);
    } catch (error) {
        console.error('Error loading suggestions:', error);
        if (suggestionsGrid) {
            suggestionsGrid.innerHTML = '<p style="grid-column: 1/-1; text-align: center; color: var(--text-muted); padding: 1.5rem 0;">Failed to load recommendations. Please check server connection.</p>';
        }
    }
}

function renderSuggestions(category = 'all') {
    if (!suggestionsGrid) return;
    suggestionsGrid.innerHTML = '';
    
    const filtered = category === 'all' 
        ? suggestionsData 
        : suggestionsData.filter(item => item.category === category);
        
    if (filtered.length === 0) {
        suggestionsGrid.innerHTML = '<p style="grid-column: 1/-1; text-align: center; color: var(--text-muted); padding: 1.5rem 0;">No suggestions available.</p>';
        return;
    }
    
    filtered.forEach(item => {
        const card = document.createElement('div');
        card.className = 'suggestion-card';
        
        const badgeClass = item.category === 'music' ? 'music' : 'video';
        const badgeLabel = item.category === 'music' ? 'Song' : 'Video';
        
        card.innerHTML = `
            <div class="suggestion-type-badge ${badgeClass}">${badgeLabel}</div>
            <div class="suggestion-thumb-container">
                <img class="suggestion-thumb" src="${escapeHtml(item.thumbnail || '/static/logo-placeholder.png')}" alt="Thumbnail" onerror="this.onerror=null;this.src='/static/logo-placeholder.png';">
                <span class="suggestion-duration">${formatSeconds(item.duration)}</span>
            </div>
            <div class="suggestion-info">
                <span class="suggestion-title" title="${escapeHtml(item.title)}">${escapeHtml(item.title)}</span>
                <span class="suggestion-uploader">${escapeHtml(item.uploader)}</span>
            </div>
        `;
        
        card.addEventListener('click', () => {
            urlInput.value = item.url;
            clearBtn.classList.remove('hidden');
            if (suggestionsSection) suggestionsSection.classList.add('hidden');
            if (videoInfo) videoInfo.classList.add('hidden');
            if (playlistInfo) playlistInfo.classList.add('hidden');
            if (searchResultsSection) searchResultsSection.classList.add('hidden');
            errorMessage.classList.add('hidden');
            fetchBtn.click();
        });
        
        suggestionsGrid.appendChild(card);
    });
}

// Setup event listeners for suggestion tab buttons
if (suggestionTabBtns) {
    suggestionTabBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            suggestionTabBtns.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            const category = btn.getAttribute('data-category');
            renderSuggestions(category);
        });
    });
}

// Setup event listener for refresh suggestions button
const refreshSuggestionsBtn = document.getElementById('refresh-suggestions-btn');
if (refreshSuggestionsBtn) {
    refreshSuggestionsBtn.addEventListener('click', async () => {
        refreshSuggestionsBtn.classList.add('spinning');
        refreshSuggestionsBtn.disabled = true;
        await loadSuggestions(true);
        refreshSuggestionsBtn.classList.remove('spinning');
        refreshSuggestionsBtn.disabled = false;
    });
}

// Initialize Application
// NOTE: isLocal is declared at the top of this file and defaults to true

async function initApp() {
    // Load recommendations/suggestions on start
    loadSuggestions();

    // 1. Fetch server config to detect mode
    try {
        const configRes = await apiFetch(`${API_BASE}/config`);
        if (configRes.ok) {
            const configData = await configRes.json();
            isLocal = configData.is_local;
            updateFFmpegStatus(configData.has_ffmpeg);
            
            if (statusDot) statusDot.className = 'status-dot green';
            if (statusLabel) statusLabel.textContent = 'Server Connected';
        }
    } catch (err) {
        console.error('Failed to load server config:', err);
        if (statusDot) statusDot.className = 'status-dot red';
        if (statusLabel) statusLabel.textContent = 'Server Offline';
    }

    // Configure UI based on Local vs Server Mode
    if (isLocal) {
        // Local mode: Show settings, hide desktop download button
        const settingsTabBtn = document.querySelector('button[data-tab="settings"]');
        if (settingsTabBtn) settingsTabBtn.style.display = 'flex';
        
        const desktopDownloadArea = document.querySelector('.desktop-download-area');
        if (desktopDownloadArea) desktopDownloadArea.style.display = 'none';
        
        // Load custom locations and populate dropdowns
        loadSettings();
    } else {
        // Server mode: Hide settings tab button in sidebar, show desktop download button
        const settingsTabBtn = document.querySelector('button[data-tab="settings"]');
        if (settingsTabBtn) settingsTabBtn.style.display = 'none';
        
        const desktopDownloadArea = document.querySelector('.desktop-download-area');
        if (desktopDownloadArea) desktopDownloadArea.style.display = 'flex';
        
        if (currentTab === 'settings') {
            switchTab('downloader');
        }
    }

    // 3. Start adaptive queue polling
    //    Fast (1.5s) when downloads active, slow (10s) when idle.
    //    Stops entirely when tab is hidden (Page Visibility API).
    function startAdaptivePolling() {
        if (queuePollingInterval) clearInterval(queuePollingInterval);
        const interval = activeDownloadsCount > 0 ? 1500 : 10000;
        queuePollingInterval = setInterval(pollQueueStatus, interval);
    }

    pollQueueStatus().then(() => startAdaptivePolling());

    // Re-adjust polling speed whenever queue data changes
    const _origRenderQueue = renderQueueList;
    renderQueueList = function(data) {
        const prevCount = activeDownloadsCount;
        _origRenderQueue(data);
        // If active count changed, adjust polling interval
        if ((prevCount > 0) !== (activeDownloadsCount > 0)) {
            startAdaptivePolling();
        }
    };

    // Pause polling when tab is hidden, resume when visible
    document.addEventListener('visibilitychange', () => {
        if (document.hidden) {
            if (queuePollingInterval) clearInterval(queuePollingInterval);
            queuePollingInterval = null;
        } else {
            pollQueueStatus().then(() => startAdaptivePolling());
        }
    });

    // Setup toggles and buttons listeners

    if (trimToggleBtn) {
        trimToggleBtn.addEventListener('click', () => {
            const isOpen = trimToggleBtn.classList.toggle('open');
            if (isOpen) {
                trimInputsWrapper.classList.remove('hidden');
            } else {
                trimInputsWrapper.classList.add('hidden');
            }
        });
    }

    if (closeSearchBtn) {
        closeSearchBtn.addEventListener('click', () => {
            searchResultsSection.classList.add('hidden');
            if (suggestionsSection) suggestionsSection.classList.remove('hidden');
        });
    }

    if (playerCloseBtn) playerCloseBtn.addEventListener('click', stopMedia);
    if (playerModalCloseX) playerModalCloseX.addEventListener('click', stopMedia);
    if (playerModal) {
        playerModal.addEventListener('click', (e) => {
            if (e.target === playerModal) {
                stopMedia();
            }
        });
    }

    if (linkModal) {
        linkModal.addEventListener('click', (e) => {
            if (e.target === linkModal) {
                linkModal.classList.add('hidden');
            }
        });
    }

    // Dismiss active modals on Escape key
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            if (playerModal && !playerModal.classList.contains('hidden')) {
                stopMedia();
            }
            if (linkModal && !linkModal.classList.contains('hidden')) {
                linkModal.classList.add('hidden');
            }
        }
    });

    if (clearQueueBtn) {
        clearQueueBtn.addEventListener('click', async () => {
            try {
                const response = await apiFetch(`${API_BASE}/active/clear`, { method: 'POST' });
                if (response.ok) {
                    pollQueueStatus();
                }
            } catch (error) {
                console.error('Failed to clear queue', error);
            }
        });
    }

    if (clearHistoryBtn) {
        clearHistoryBtn.addEventListener('click', async () => {
            if (!confirm('Are you sure you want to clear your completed downloads list? The downloaded files on disk will NOT be deleted.')) return;
            try {
                const response = await apiFetch(`${API_BASE}/history/clear`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ delete_files: false })
                });
                if (response.ok) {
                    loadHistory();
                }
            } catch (error) {
                console.error('Failed to clear history', error);
            }
        });
    }


}

document.addEventListener('DOMContentLoaded', initApp);
