/**
 * storage.js – Shared localStorage helpers for StockVN frontend.
 */

/**
 * Get or create a unique web client ID for watchlist/portfolio.
 */

window.onTelegramAuth = function(user) {
  localStorage.setItem('telegram_chat_id', user.id);
  localStorage.setItem('telegram_user', JSON.stringify(user));
  alert('Đăng nhập thành công! Đã đồng bộ với Telegram của ' + user.first_name);
  location.reload();
}
function logoutTelegram() {
  localStorage.removeItem('telegram_chat_id');
  localStorage.removeItem('telegram_user');
  location.reload();
}
function getClientId() {
  const tgId = localStorage.getItem('telegram_chat_id');
  if (tgId) return String(tgId);

  let id = localStorage.getItem('stockvn_client_id');
  if (!id) {
    const bytes = new Uint8Array(16);
    crypto.getRandomValues(bytes);
    id = 'web_' + Array.from(bytes).map(b => b.toString(16).padStart(2, '0')).join('');
    localStorage.setItem('stockvn_client_id', id);
  }
  return id;
}

/**
 * Escape HTML to prevent XSS.
 */
function esc(str) {
  if (str == null) return '';
  const div = document.createElement('div');
  div.textContent = String(str);
  return div.innerHTML;
}

/**
 * Clean a stock symbol – uppercase, trim.
 */
function cleanSymbol(sym) {
  return (sym || '').trim().toUpperCase().replace(/[^A-Z0-9]/g, '');
}

/**
 * Format price with thousands separator.
 */
function formatPrice(price) {
  if (price == null || isNaN(price)) return '—';
  return Number(price).toLocaleString('vi-VN');
}

/**
 * Format change percentage with sign and color class.
 */
function formatChange(pct) {
  if (pct == null || isNaN(pct)) return { text: '—', cls: '' };
  const sign = pct >= 0 ? '+' : '';
  return {
    text: `${sign}${pct.toFixed(2)}%`,
    cls: pct > 0 ? 'up' : pct < 0 ? 'down' : '',
  };
}
