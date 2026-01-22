/**
 * Portfolio Chat Analytics Dashboard
 */

// State
let currentPage = 0;
const pageSize = 20;
let totalConversations = 0;
let activityChart = null;

// DOM Elements
const elements = {
    startDate: document.getElementById('start-date'),
    endDate: document.getElementById('end-date'),
    applyFilter: document.getElementById('apply-filter'),
    resetFilter: document.getElementById('reset-filter'),
    granularity: document.getElementById('granularity'),
    conversationsList: document.getElementById('conversations-list'),
    domainsList: document.getElementById('domains-list'),
    prevPage: document.getElementById('prev-page'),
    nextPage: document.getElementById('next-page'),
    pageInfo: document.getElementById('page-info'),
    modal: document.getElementById('modal'),
    modalBody: document.getElementById('modal-body'),
    closeModal: document.getElementById('close-modal'),
};

// Initialize
document.addEventListener('DOMContentLoaded', () => {
    // Set default date range (last 30 days)
    const today = new Date();
    const thirtyDaysAgo = new Date(today);
    thirtyDaysAgo.setDate(thirtyDaysAgo.getDate() - 30);

    elements.endDate.value = formatDateForInput(today);
    elements.startDate.value = formatDateForInput(thirtyDaysAgo);

    // Load initial data
    loadDashboard();

    // Event listeners
    elements.applyFilter.addEventListener('click', loadDashboard);
    elements.resetFilter.addEventListener('click', resetFilters);
    elements.granularity.addEventListener('change', loadTimeseries);
    elements.prevPage.addEventListener('click', () => changePage(-1));
    elements.nextPage.addEventListener('click', () => changePage(1));
    elements.closeModal.addEventListener('click', closeModal);
    elements.modal.addEventListener('click', (e) => {
        if (e.target === elements.modal) closeModal();
    });

    // Keyboard shortcuts
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && elements.modal.classList.contains('active')) {
            closeModal();
        }
    });
});

// Helper functions
function formatDateForInput(date) {
    return date.toISOString().split('T')[0];
}

function formatDateTime(isoString) {
    if (!isoString) return '-';
    const date = new Date(isoString);
    return date.toLocaleString();
}

function formatDuration(ms) {
    if (!ms || ms === 0) return '-';
    if (ms < 1000) return `${Math.round(ms)}ms`;
    return `${(ms / 1000).toFixed(2)}s`;
}

function getDateParams() {
    const params = new URLSearchParams();
    if (elements.startDate.value) {
        params.set('start_date', elements.startDate.value);
    }
    if (elements.endDate.value) {
        params.set('end_date', elements.endDate.value);
    }
    return params;
}

// API calls
async function fetchStats() {
    const params = getDateParams();
    const response = await fetch(`/admin/analytics/stats?${params}`);
    if (!response.ok) throw new Error('Failed to fetch stats');
    return response.json();
}

async function fetchTimeseries() {
    const params = getDateParams();
    params.set('granularity', elements.granularity.value);
    const response = await fetch(`/admin/analytics/timeseries?${params}`);
    if (!response.ok) throw new Error('Failed to fetch timeseries');
    return response.json();
}

async function fetchConversations(offset = 0) {
    const params = getDateParams();
    params.set('limit', pageSize);
    params.set('offset', offset);
    const response = await fetch(`/admin/analytics/conversations?${params}`);
    if (!response.ok) throw new Error('Failed to fetch conversations');
    return response.json();
}

async function fetchConversationDetail(id) {
    const response = await fetch(`/admin/analytics/conversations/${id}`);
    if (!response.ok) throw new Error('Failed to fetch conversation');
    return response.json();
}

// Load functions
async function loadDashboard() {
    await Promise.all([
        loadStats(),
        loadTimeseries(),
        loadConversations(),
    ]);
}

async function loadStats() {
    try {
        const stats = await fetchStats();

        document.getElementById('total-conversations').textContent = stats.total_conversations.toLocaleString();
        document.getElementById('total-messages').textContent = stats.total_messages.toLocaleString();
        document.getElementById('avg-messages').textContent = stats.avg_messages_per_conversation.toFixed(1);
        document.getElementById('median-messages').textContent = stats.median_messages_per_conversation.toFixed(1);
        document.getElementById('avg-response-time').textContent = formatDuration(stats.avg_response_time_ms);
        document.getElementById('total-blocked').textContent = stats.total_blocked.toLocaleString();

        // Render domains
        renderDomains(stats.domains_breakdown);
    } catch (error) {
        console.error('Failed to load stats:', error);
    }
}

async function loadTimeseries() {
    try {
        const data = await fetchTimeseries();
        renderChart(data);
    } catch (error) {
        console.error('Failed to load timeseries:', error);
    }
}

async function loadConversations() {
    elements.conversationsList.innerHTML = '<p class="loading">Loading...</p>';

    try {
        const data = await fetchConversations(currentPage * pageSize);
        totalConversations = data.pagination.total;
        renderConversations(data.conversations);
        updatePagination(data.pagination);
    } catch (error) {
        console.error('Failed to load conversations:', error);
        elements.conversationsList.innerHTML = '<p class="error">Failed to load conversations</p>';
    }
}

// Render functions
function renderDomains(domains) {
    if (!domains || Object.keys(domains).length === 0) {
        elements.domainsList.innerHTML = '<p class="empty">No domain data available</p>';
        return;
    }

    const sorted = Object.entries(domains).sort((a, b) => b[1] - a[1]);
    elements.domainsList.innerHTML = sorted.map(([domain, count]) => `
        <div class="domain-badge">
            ${escapeHtml(domain)}
            <span class="count">${count}</span>
        </div>
    `).join('');
}

function renderChart(data) {
    const ctx = document.getElementById('activity-chart').getContext('2d');

    if (activityChart) {
        activityChart.destroy();
    }

    const labels = data.map(d => {
        const date = new Date(d.timestamp);
        const granularity = elements.granularity.value;
        if (granularity === 'hour') {
            return date.toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit' });
        } else if (granularity === 'week') {
            return date.toLocaleDateString([], { month: 'short', day: 'numeric' });
        }
        return date.toLocaleDateString([], { month: 'short', day: 'numeric' });
    });

    activityChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [
                {
                    label: 'Conversations',
                    data: data.map(d => d.conversations),
                    borderColor: '#e94560',
                    backgroundColor: 'rgba(233, 69, 96, 0.1)',
                    fill: true,
                    tension: 0.3,
                },
                {
                    label: 'Messages',
                    data: data.map(d => d.messages),
                    borderColor: '#4ade80',
                    backgroundColor: 'rgba(74, 222, 128, 0.1)',
                    fill: true,
                    tension: 0.3,
                },
            ],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    labels: {
                        color: '#eaeaea',
                    },
                },
            },
            scales: {
                x: {
                    ticks: { color: '#a0a0a0' },
                    grid: { color: 'rgba(255, 255, 255, 0.1)' },
                },
                y: {
                    beginAtZero: true,
                    ticks: { color: '#a0a0a0' },
                    grid: { color: 'rgba(255, 255, 255, 0.1)' },
                },
            },
        },
    });
}

function renderConversations(conversations) {
    if (!conversations || conversations.length === 0) {
        elements.conversationsList.innerHTML = '<p class="empty">No conversations found</p>';
        return;
    }

    elements.conversationsList.innerHTML = conversations.map(conv => `
        <div class="conversation-item" data-id="${escapeHtml(conv.id)}">
            <div class="conversation-info">
                <div class="conversation-id">${escapeHtml(conv.id)}</div>
                <div class="conversation-meta">
                    <span class="turns">${conv.total_turns} turns</span>
                    <span>${conv.message_count} messages</span>
                    <span>${formatDateTime(conv.started_at)}</span>
                    ${conv.blocked_at_layer ? `<span class="blocked">Blocked at ${escapeHtml(conv.blocked_at_layer)}</span>` : ''}
                </div>
            </div>
            <div class="conversation-domains">
                ${conv.domains_used.map(d => `<span class="domain-tag">${escapeHtml(d)}</span>`).join('')}
            </div>
        </div>
    `).join('');

    // Add click handlers
    document.querySelectorAll('.conversation-item').forEach(item => {
        item.addEventListener('click', () => openConversation(item.dataset.id));
    });
}

function updatePagination(pagination) {
    const totalPages = Math.ceil(pagination.total / pageSize);
    const currentPageNum = Math.floor(pagination.offset / pageSize) + 1;

    elements.pageInfo.textContent = `Page ${currentPageNum} of ${totalPages || 1}`;
    elements.prevPage.disabled = pagination.offset === 0;
    elements.nextPage.disabled = !pagination.has_more;
}

// Conversation detail
async function openConversation(id) {
    elements.modal.classList.add('active');
    elements.modalBody.innerHTML = '<p class="loading">Loading...</p>';

    try {
        const conv = await fetchConversationDetail(id);
        renderConversationDetail(conv);
    } catch (error) {
        console.error('Failed to load conversation:', error);
        elements.modalBody.innerHTML = '<p class="error">Failed to load conversation</p>';
    }
}

function renderConversationDetail(conv) {
    const metaHtml = `
        <div class="conversation-detail-meta">
            <div class="meta-item">
                <div class="label">ID</div>
                <div class="value" style="font-family: monospace; font-size: 0.85rem;">${escapeHtml(conv.id)}</div>
            </div>
            <div class="meta-item">
                <div class="label">Started</div>
                <div class="value">${formatDateTime(conv.started_at)}</div>
            </div>
            <div class="meta-item">
                <div class="label">Last Activity</div>
                <div class="value">${formatDateTime(conv.last_activity)}</div>
            </div>
            <div class="meta-item">
                <div class="label">Total Turns</div>
                <div class="value">${conv.total_turns}</div>
            </div>
            <div class="meta-item">
                <div class="label">Avg Response</div>
                <div class="value">${formatDuration(conv.total_turns > 0 ? conv.total_response_time_ms / conv.total_turns : 0)}</div>
            </div>
            ${conv.blocked_at_layer ? `
            <div class="meta-item">
                <div class="label">Blocked At</div>
                <div class="value" style="color: var(--warning);">${escapeHtml(conv.blocked_at_layer)}</div>
            </div>
            ` : ''}
        </div>
    `;

    const messagesHtml = conv.messages.map(msg => `
        <div class="message ${escapeHtml(msg.role)}">
            <div class="message-header">
                <span>${msg.role === 'user' ? 'User' : 'Assistant'}</span>
                <span>${formatDateTime(msg.timestamp)}</span>
            </div>
            <div class="message-content">${escapeHtml(msg.content)}</div>
            ${msg.domain || msg.response_time_ms ? `
            <div class="message-meta">
                ${msg.domain ? `Domain: ${escapeHtml(msg.domain)}` : ''}
                ${msg.response_time_ms ? ` | Response: ${formatDuration(msg.response_time_ms)}` : ''}
            </div>
            ` : ''}
        </div>
    `).join('');

    elements.modalBody.innerHTML = `
        ${metaHtml}
        <div class="message-list">
            ${messagesHtml || '<p class="empty">No messages in this conversation</p>'}
        </div>
    `;
}

function closeModal() {
    elements.modal.classList.remove('active');
}

// Pagination
function changePage(delta) {
    currentPage = Math.max(0, currentPage + delta);
    loadConversations();
}

// Filter functions
function resetFilters() {
    const today = new Date();
    const thirtyDaysAgo = new Date(today);
    thirtyDaysAgo.setDate(thirtyDaysAgo.getDate() - 30);

    elements.endDate.value = formatDateForInput(today);
    elements.startDate.value = formatDateForInput(thirtyDaysAgo);
    currentPage = 0;

    loadDashboard();
}

// Security
function escapeHtml(text) {
    if (text === null || text === undefined) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}
