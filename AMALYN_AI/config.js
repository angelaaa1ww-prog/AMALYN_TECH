// config.js — AMALYN Network Configuration
// This file is loaded by all portals to detect the right API URL

const AMALYN_CONFIG = (() => {
    const hostname = location.hostname

    // Running locally
    const isLocal = hostname === 'localhost' ||
                    hostname === '127.0.0.1' ||
                    hostname.startsWith('192.168') ||
                    hostname.startsWith('10.') ||
                    hostname === ''

    // Local network IP — change this to your machine's IP
    // Find it by running: ipconfig (Windows) or ifconfig (Mac)
    const LOCAL_IP = '192.168.1.100'
    const LOCAL_PORT = '8000'

    // Your Render API URL
    const RENDER_API = 'https://amalyn-tech.onrender.com'

    let apiUrl, wsUrl

    if(location.protocol === 'file:'){
        // Opened directly as file — use localhost
        apiUrl = `http://localhost:${LOCAL_PORT}`
        wsUrl = `ws://localhost:${LOCAL_PORT}/ws`
    } else if(isLocal){
        // Running on local network
        apiUrl = `http://${hostname}:${LOCAL_PORT}`
        wsUrl = `ws://${hostname}:${LOCAL_PORT}/ws`
    } else {
        // Running from Render or remote — use Render API
        // Note: WebSocket needs local for live audio
        apiUrl = RENDER_API
        wsUrl = `ws://localhost:${LOCAL_PORT}/ws`
    }

    return { apiUrl, wsUrl, isLocal, LOCAL_IP, LOCAL_PORT, RENDER_API }
})()

console.log('[AMALYN] API:', AMALYN_CONFIG.apiUrl)
console.log('[AMALYN] WS:', AMALYN_CONFIG.wsUrl)