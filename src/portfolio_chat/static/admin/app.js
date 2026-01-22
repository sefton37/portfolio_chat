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
    conversationsList: document.getElementById('conversations-list'),
    domainsList: document.getElementById('domains-list'),
    prevPage: document.getElementById('prev-page'),
    nextPage: document.getElementById('next-page'),
    pageInfo: document.getElementById('page-info'),
    modal: document.getElementById('modal'),
    modalBody: document.getElementById('modal-body'),
    closeModal: document.getElementById('close-modal'),
    inboxList: document.getElementById('inbox-list'),
    inboxCount: document.getElementById('inbox-count'),
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
    params.set('granularity', 'day');
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
        loadInbox(),
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

    // Convert data to scatter plot format with date on x-axis
    const conversationPoints = data.map(d => ({
        x: d.timestamp.split('T')[0],  // Just the date part
        y: d.conversations
    }));

    const messagePoints = data.map(d => ({
        x: d.timestamp.split('T')[0],
        y: d.messages
    }));

    activityChart = new Chart(ctx, {
        type: 'scatter',
        data: {
            datasets: [
                {
                    label: 'Conversations',
                    data: conversationPoints,
                    borderColor: '#e94560',
                    backgroundColor: '#e94560',
                    pointRadius: 8,
                    pointHoverRadius: 10,
                },
                {
                    label: 'Messages',
                    data: messagePoints,
                    borderColor: '#4ade80',
                    backgroundColor: '#4ade80',
                    pointRadius: 8,
                    pointHoverRadius: 10,
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
                tooltip: {
                    callbacks: {
                        label: function(context) {
                            return `${context.dataset.label}: ${context.parsed.y}`;
                        }
                    }
                }
            },
            scales: {
                x: {
                    type: 'category',
                    title: {
                        display: true,
                        text: 'Date',
                        color: '#eaeaea',
                    },
                    ticks: { color: '#a0a0a0' },
                    grid: { color: 'rgba(255, 255, 255, 0.1)' },
                },
                y: {
                    beginAtZero: true,
                    title: {
                        display: true,
                        text: 'Count',
                        color: '#eaeaea',
                    },
                    ticks: {
                        color: '#a0a0a0',
                        stepSize: 1,
                    },
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

// Inbox functions
async function fetchInbox() {
    const response = await fetch('/admin/inbox?limit=50');
    if (!response.ok) throw new Error('Failed to fetch inbox');
    return response.json();
}

async function fetchInboxMessage(id) {
    const response = await fetch(`/admin/inbox/${id}`);
    if (!response.ok) throw new Error('Failed to fetch message');
    return response.json();
}

async function loadInbox() {
    elements.inboxList.innerHTML = '<p class="loading">Loading...</p>';

    try {
        const data = await fetchInbox();
        elements.inboxCount.textContent = data.total;
        renderInbox(data.messages);
    } catch (error) {
        console.error('Failed to load inbox:', error);
        elements.inboxList.innerHTML = '<p class="error">Failed to load inbox</p>';
    }
}

function renderInbox(messages) {
    if (!messages || messages.length === 0) {
        elements.inboxList.innerHTML = '<p class="empty">No messages in inbox</p>';
        return;
    }

    elements.inboxList.innerHTML = messages.map(msg => `
        <div class="inbox-item" data-id="${escapeHtml(msg.id)}">
            <div class="inbox-item-header">
                <span class="inbox-item-sender">${escapeHtml(msg.sender_name || 'Anonymous')}</span>
                <span class="inbox-item-time">${formatDateTime(msg.timestamp)}</span>
            </div>
            <div class="inbox-item-preview">${escapeHtml(msg.message.substring(0, 150))}${msg.message.length > 150 ? '...' : ''}</div>
            <div class="inbox-item-meta">
                ${msg.sender_email ? `<span>Email: ${escapeHtml(msg.sender_email)}</span>` : ''}
                ${msg.conversation_id ? `<a href="#" class="view-conversation" data-conv-id="${escapeHtml(msg.conversation_id)}">View Conversation</a>` : ''}
            </div>
        </div>
    `).join('');

    // Add click handlers for inbox items
    document.querySelectorAll('.inbox-item').forEach(item => {
        item.addEventListener('click', (e) => {
            // Don't open modal if clicking the conversation link
            if (e.target.classList.contains('view-conversation')) {
                e.preventDefault();
                const convId = e.target.dataset.convId;
                openConversation(convId);
                return;
            }
            openInboxMessage(item.dataset.id);
        });
    });
}

async function openInboxMessage(id) {
    elements.modal.classList.add('active');
    elements.modalBody.innerHTML = '<p class="loading">Loading...</p>';

    try {
        const msg = await fetchInboxMessage(id);
        renderInboxMessageDetail(msg);
    } catch (error) {
        console.error('Failed to load message:', error);
        elements.modalBody.innerHTML = '<p class="error">Failed to load message</p>';
    }
}

function renderInboxMessageDetail(msg) {
    elements.modalBody.innerHTML = `
        <div class="inbox-detail-meta">
            <div class="meta-item">
                <div class="label">From</div>
                <div class="value">${escapeHtml(msg.sender_name || 'Anonymous')}</div>
            </div>
            <div class="meta-item">
                <div class="label">Email</div>
                <div class="value">${escapeHtml(msg.sender_email || 'Not provided')}</div>
            </div>
            <div class="meta-item">
                <div class="label">Received</div>
                <div class="value">${formatDateTime(msg.timestamp)}</div>
            </div>
            <div class="meta-item">
                <div class="label">Message ID</div>
                <div class="value" style="font-family: monospace; font-size: 0.85rem;">${escapeHtml(msg.id)}</div>
            </div>
            ${msg.conversation_id ? `
            <div class="meta-item">
                <div class="label">Conversation</div>
                <div class="value"><a href="#" onclick="closeModal(); openConversation('${escapeHtml(msg.conversation_id)}'); return false;" style="color: var(--accent);">View</a></div>
            </div>
            ` : ''}
        </div>
        <h3 style="margin-bottom: 0.5rem;">Message</h3>
        <div class="inbox-message-full">${escapeHtml(msg.message)}</div>
        ${msg.context ? `
        <h3 style="margin-top: 1rem; margin-bottom: 0.5rem;">Conversation Context</h3>
        <div class="inbox-message-full">${escapeHtml(msg.context)}</div>
        ` : ''}
    `;
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
