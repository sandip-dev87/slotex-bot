// ═════════════════════════════════════════════
// SLOTEX ADMIN — App JS
// ═════════════════════════════════════════════

// ─── SIDEBAR TOGGLE ───
function toggleSidebar() {
  document.getElementById('sidebar').classList.toggle('open');
}

// Close sidebar when clicking outside on mobile
document.addEventListener('click', (e) => {
  const sidebar = document.getElementById('sidebar');
  const toggle = document.querySelector('.menu-toggle');
  if (window.innerWidth <= 900 && sidebar && sidebar.classList.contains('open')) {
    if (!sidebar.contains(e.target) && !toggle.contains(e.target)) {
      sidebar.classList.remove('open');
    }
  }
});

// ─── TOASTS ───
function showToast(msg, type = 'info', duration = 3000) {
  const container = document.getElementById('toast-container');
  const toast = document.createElement('div');
  toast.className = `toast ${type}`;
  toast.textContent = msg;
  container.appendChild(toast);
  setTimeout(() => {
    toast.classList.add('out');
    setTimeout(() => toast.remove(), 300);
  }, duration);
}

// ─── MODAL ───
let modalResolve = null;

function openModal(title, bodyHTML, onConfirm) {
  document.getElementById('modal-title').textContent = title;
  document.getElementById('modal-body').innerHTML = bodyHTML;
  document.getElementById('modal-overlay').classList.add('open');
  modalResolve = onConfirm;
}

function closeModal(e) {
  if (e && e.target !== document.getElementById('modal-overlay')) return;
  document.getElementById('modal-overlay').classList.remove('open');
  modalResolve = null;
}

document.getElementById('modal-confirm').addEventListener('click', () => {
  if (modalResolve) {
    const result = modalResolve();
    if (result !== false) {
      document.getElementById('modal-overlay').classList.remove('open');
      modalResolve = null;
    }
  }
});

// ─── API HELPER ───
async function apiCall(url, body = null) {
  try {
    const opts = {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' }
    };
    if (body) opts.body = JSON.stringify(body);
    const r = await fetch(url, opts);
    const data = await r.json();
    return { ok: r.ok, data };
  } catch (e) {
    return { ok: false, data: { error: 'Network error' } };
  }
}

// ─── WITHDRAWAL APPROVE ───
async function approveWd(id) {
  const row = document.getElementById(`wd-row-${id}`);
  if (row) row.style.opacity = '0.5';

  const { ok, data } = await apiCall(`/api/withdrawals/${id}/approve`);
  if (ok && data.ok) {
    showToast('✓ Withdrawal approved', 'success');
    if (row) { row.style.transition = 'all 0.3s'; row.style.transform = 'translateX(20px)'; setTimeout(() => row.remove(), 300); }
  } else {
    showToast(data.error || 'Failed', 'error');
    if (row) row.style.opacity = '1';
  }
}

// ─── WITHDRAWAL REJECT ───
function rejectWd(id) {
  openModal('Reject Withdrawal', `
    <textarea id="reject-reason" rows="3" placeholder="Enter reason..."></textarea>
  `, async () => {
    const reason = document.getElementById('reject-reason').value.trim();
    if (!reason) { showToast('Reason required', 'error'); return false; }
    const { ok, data } = await apiCall(`/api/withdrawals/${id}/reject`, { reason });
    if (ok && data.ok) {
      showToast('✗ Withdrawal rejected', 'info');
      const row = document.getElementById(`wd-row-${id}`);
      if (row) { row.style.transition = 'all 0.3s'; row.style.transform = 'translateX(20px)'; setTimeout(() => row.remove(), 300); }
      return true;
    }
    showToast(data.error || 'Failed', 'error');
    return false;
  });
}

// ─── MEMBERSHIP APPROVE ───
async function approveMbr(id) {
  const row = document.getElementById(`mbr-row-${id}`);
  if (row) row.style.opacity = '0.5';

  const { ok, data } = await apiCall(`/api/memberships/${id}/approve`);
  if (ok && data.ok) {
    showToast('✓ Membership approved', 'success');
    if (row) { row.style.transition = 'all 0.3s'; row.style.transform = 'translateX(20px)'; setTimeout(() => row.remove(), 300); }
  } else {
    showToast(data.error || 'Failed', 'error');
    if (row) row.style.opacity = '1';
  }
}

// ─── MEMBERSHIP REJECT ───
function rejectMbr(id) {
  openModal('Reject Membership', `
    <textarea id="reject-reason" rows="3" placeholder="Enter reason..."></textarea>
  `, async () => {
    const reason = document.getElementById('reject-reason').value.trim();
    if (!reason) { showToast('Reason required', 'error'); return false; }
    const { ok, data } = await apiCall(`/api/memberships/${id}/reject`, { reason });
    if (ok && data.ok) {
      showToast('✗ Membership rejected', 'info');
      const row = document.getElementById(`mbr-row-${id}`);
      if (row) { row.style.transition = 'all 0.3s'; row.style.transform = 'translateX(20px)'; setTimeout(() => row.remove(), 300); }
      return true;
    }
    showToast(data.error || 'Failed', 'error');
    return false;
  });
}

// ─── ORDER APPROVE ───
function approveOrd(id) {
  openModal('Approve Order', `
    <label style="display:block;margin-bottom:8px;font-size:13px;color:#94a3b8;">Reward Amount (₹)</label>
    <input id="reward-input" type="number" min="1" step="0.01" placeholder="e.g. 50" />
  `, async () => {
    const reward = parseFloat(document.getElementById('reward-input').value);
    if (!reward || reward <= 0) { showToast('Valid reward required', 'error'); return false; }
    const { ok, data } = await apiCall(`/api/orders/${id}/approve`, { reward });
    if (ok && data.ok) {
      showToast(`✓ Order approved (₹${reward})`, 'success');
      const row = document.getElementById(`ord-row-${id}`);
      if (row) { row.style.transition = 'all 0.3s'; row.style.transform = 'translateX(20px)'; setTimeout(() => row.remove(), 300); }
      return true;
    }
    showToast(data.error || 'Failed', 'error');
    return false;
  });
}

// ─── ORDER REJECT ───
function rejectOrd(id) {
  openModal('Reject Order', `
    <textarea id="reject-reason" rows="3" placeholder="Enter reason..."></textarea>
  `, async () => {
    const reason = document.getElementById('reject-reason').value.trim();
    if (!reason) { showToast('Reason required', 'error'); return false; }
    const { ok, data } = await apiCall(`/api/orders/${id}/reject`, { reason });
    if (ok && data.ok) {
      showToast('✗ Order rejected', 'info');
      const row = document.getElementById(`ord-row-${id}`);
      if (row) { row.style.transition = 'all 0.3s'; row.style.transform = 'translateX(20px)'; setTimeout(() => row.remove(), 300); }
      return true;
    }
    showToast(data.error || 'Failed', 'error');
    return false;
  });
}

// ─── ANIMATED COUNTERS ───
document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('[data-count]').forEach(el => {
    const target = parseInt(el.dataset.count) || 0;
    if (target === 0) return;
    let current = 0;
    const step = Math.max(1, Math.floor(target / 40));
    const timer = setInterval(() => {
      current += step;
      if (current >= target) { current = target; clearInterval(timer); }
      el.textContent = current;
    }, 20);
  });
});

// ═════════════════════════════════════════════
// CLEAR CACHE
// ═════════════════════════════════════════════
async function clearCache() {
  if (!confirm('Cache clear karna hai? Next load pe fresh data aayega (thoda slow hoga).')) return;

  try {
    const r = await fetch('/api/cache/clear', { method: 'POST' });
    const data = await r.json();

    if (r.ok && data.ok) {
      showToast('✓ Cache cleared! Fresh data on next load.', 'success');
      setTimeout(() => location.reload(), 800);
    } else {
      showToast('Failed to clear cache', 'error');
    }
  } catch (e) {
    showToast('Network error', 'error');
  }
}
