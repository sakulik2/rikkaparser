let currentConv = -1;

function showConversation(index) {
    // Hide all
    document.getElementById('welcome').style.display = 'none';
    document.querySelectorAll('.conv-view').forEach(el => el.style.display = 'none');
    document.querySelectorAll('.conv-item').forEach(el => el.classList.remove('active'));
    // Show selected
    const view = document.getElementById('conv-' + index);
    if (view) {
        view.style.display = 'block';
        view.scrollTop = 0;
    }
    const items = document.querySelectorAll('.conv-item[data-index="' + index + '"]');
    items.forEach(el => el.classList.add('active'));
    currentConv = index;
    // Close sidebar on mobile
    document.getElementById('sidebar').classList.remove('open');
}

function filterConversations() {
    const query = document.getElementById('searchBox').value.toLowerCase();
    document.querySelectorAll('.conv-item').forEach(item => {
        const title = (item.getAttribute('data-title') || '').toLowerCase();
        item.style.display = title.includes(query) ? '' : 'none';
    });
}

function toggleSidebar() {
    document.getElementById('sidebar').classList.toggle('open');
}

// Keyboard navigation
document.addEventListener('keydown', (e) => {
    if (e.target.tagName === 'INPUT') return;
    const items = [...document.querySelectorAll('.conv-item')].filter(el => el.style.display !== 'none');
    if (!items.length) return;
    let idx = items.findIndex(el => el.classList.contains('active'));
    if (e.key === 'ArrowDown' || e.key === 'j') {
        e.preventDefault();
        idx = Math.min(idx + 1, items.length - 1);
        showConversation(parseInt(items[idx].getAttribute('data-index')));
        items[idx].scrollIntoView({ block: 'nearest' });
    } else if (e.key === 'ArrowUp' || e.key === 'k') {
        e.preventDefault();
        idx = Math.max(idx - 1, 0);
        showConversation(parseInt(items[idx].getAttribute('data-index')));
        items[idx].scrollIntoView({ block: 'nearest' });
    }
});
