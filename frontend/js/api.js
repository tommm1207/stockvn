
// API configuration
// When deploying to Cloudflare, change this to your backend domain (e.g., 'https://api.stockvn.com')
// Leave empty string '' to use the same domain (for local testing)
const API_BASE_URL = '';

function getApiUrl(endpoint) {
    if (API_BASE_URL) {
        return API_BASE_URL + endpoint;
    }
    return endpoint;
}
/**
 * api.js – Shared API helper for StockVN frontend.
 * Centralized fetch with error handling, loading states, and retry.
 */

const API = {
  /**
   * Make an API request with error handling.
   * @param {string} url - API endpoint (e.g., '/api/stock/VNM')
   * @param {object} options - fetch options
   * @returns {Promise<any>} parsed JSON response
   */
  async fetch(url, options = {}) {
    const defaults = {
      headers: { 'Content-Type': 'application/json' },
    };
    const config = { ...defaults, ...options };
    if (config.body && typeof config.body === 'object') {
      config.body = JSON.stringify(config.body);
    }

    try {
      const response = await fetch(url, config);
      if (!response.ok) {
        const err = await response.json().catch(() => ({ detail: response.statusText }));
        throw new Error(err.detail || `HTTP ${response.status}`);
      }
      return await response.json();
    } catch (error) {
      if (error.name === 'TypeError' && error.message.includes('fetch')) {
        throw new Error('Không thể kết nối server. Kiểm tra backend đang chạy.');
      }
      throw error;
    }
  },

  get(url) { return this.fetch(url); },
  post(url, body) { return this.fetch(url, { method: 'POST', body }); },
  put(url, body) { return this.fetch(url, { method: 'PUT', body }); },
  delete(url) { return this.fetch(url, { method: 'DELETE' }); },
};


/**
 * Show/hide loading state in a container element.
 */
function showLoading(container, message = 'Đang tải...') {
  if (typeof container === 'string') container = document.getElementById(container);
  if (!container) return;
  container.innerHTML = `
    <div class="loading-overlay">
      <div class="spinner"></div>
      <span>${esc(message)}</span>
    </div>`;
}

function showEmpty(container, message = 'Không có dữ liệu') {
  if (typeof container === 'string') container = document.getElementById(container);
  if (!container) return;
  container.innerHTML = `
    <div class="loading-overlay" style="color:var(--txt2)">
      <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
        <circle cx="12" cy="12" r="10"/><path d="M8 15h8M9 9h.01M15 9h.01"/>
      </svg>
      <span>${esc(message)}</span>
    </div>`;
}

function showError(container, message = 'Đã xảy ra lỗi') {
  if (typeof container === 'string') container = document.getElementById(container);
  if (!container) return;
  container.innerHTML = `
    <div class="loading-overlay" style="color:var(--red)">
      <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
        <circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/>
      </svg>
      <span>${esc(message)}</span>
    </div>`;
}

/**
 * Show a toast notification.
 */
function showToast(message, type = 'info', duration = 3000) {
  let container = document.querySelector('.toast-container');
  if (!container) {
    container = document.createElement('div');
    container.className = 'toast-container';
    document.body.appendChild(container);
  }
  const toast = document.createElement('div');
  toast.className = `toast ${type}`;
  toast.textContent = message;
  container.appendChild(toast);
  setTimeout(() => { toast.remove(); }, duration);
}
