/**
 * CivicConnect Core Utilities & Designer Theme Switcher
 */

(function () {
    // 1. Synchronous early theme apply to prevent flash of wrong mode
    const savedTheme = localStorage.getItem('civic_theme');
    const systemPrefersDark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
    const initialTheme = savedTheme || (systemPrefersDark ? 'dark' : 'light');

    document.documentElement.setAttribute('data-theme', initialTheme);
    document.documentElement.setAttribute('data-bs-theme', initialTheme);

    // 2. Main DOM initialization
    document.addEventListener('DOMContentLoaded', function () {
        initThemeSwitcher();
        initAlertAutoDismiss();
        initEmergencyBroadcastSystem();
        initNotificationCenter();
    });

    // Theme Switcher Logic
    function initThemeSwitcher() {
        const currentTheme = document.documentElement.getAttribute('data-theme') || 'light';

        // Check if floating widget already exists
        if (!document.getElementById('civicThemeWidget')) {
            const widget = document.createElement('div');
            widget.id = 'civicThemeWidget';
            widget.className = 'civic-theme-widget';
            widget.setAttribute('title', 'Toggle Light / Dark Mode');
            widget.setAttribute('aria-label', 'Toggle theme');
            widget.setAttribute('role', 'button');
            widget.setAttribute('tabindex', '0');
            widget.innerHTML = `
                <div class="civic-theme-switch-track">
                    <span class="opacity-75">☀️</span>
                    <span class="opacity-75">🌙</span>
                    <div class="civic-theme-switch-thumb">
                        <i class="bi ${currentTheme === 'dark' ? 'bi-moon-stars-fill' : 'bi-sun-fill'}"></i>
                    </div>
                </div>
                <span class="civic-theme-label d-none d-sm-inline">${currentTheme === 'dark' ? 'Dark' : 'Light'}</span>
            `;

            widget.addEventListener('click', toggleTheme);
            widget.addEventListener('keydown', function (e) {
                if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    toggleTheme();
                }
            });
            document.body.appendChild(widget);
        }

        // Attach to any inline theme toggle buttons (e.g. in navbars)
        document.querySelectorAll('.theme-toggle-btn').forEach(btn => {
            btn.addEventListener('click', toggleTheme);
        });
    }

    function toggleTheme() {
        const current = document.documentElement.getAttribute('data-theme') || 'light';
        const nextTheme = current === 'dark' ? 'light' : 'dark';

        document.documentElement.setAttribute('data-theme', nextTheme);
        document.documentElement.setAttribute('data-bs-theme', nextTheme);
        localStorage.setItem('civic_theme', nextTheme);

        // Update widget thumb icon & text
        const widget = document.getElementById('civicThemeWidget');
        if (widget) {
            const icon = widget.querySelector('.civic-theme-switch-thumb i');
            const label = widget.querySelector('.civic-theme-label');
            if (icon) {
                icon.className = `bi ${nextTheme === 'dark' ? 'bi-moon-stars-fill' : 'bi-sun-fill'}`;
            }
            if (label) {
                label.textContent = nextTheme === 'dark' ? 'Dark' : 'Light';
            }
        }

        // Dispatch event for any map or chart listeners
        window.dispatchEvent(new CustomEvent('civicThemeChanged', { detail: { theme: nextTheme } }));
    }

    // ==========================================================================
    // Real-Time In-App Notification Center
    // ==========================================================================
    let notifDrawerVisible = false;

    function initNotificationCenter() {
        fetchNotifications();
        setInterval(fetchNotifications, 25000);

        // Close drawer when clicking outside
        document.addEventListener('click', function (e) {
            const drawer = document.getElementById('civicNotifDrawer');
            const bell = document.getElementById('civicNotifBellBtn');
            if (drawer && notifDrawerVisible) {
                if (!drawer.contains(e.target) && (!bell || !bell.contains(e.target))) {
                    drawer.classList.remove('show');
                    notifDrawerVisible = false;
                }
            }
        });
    }

    async function fetchNotifications() {
        try {
            const res = await fetch('/api/notifications');
            if (!res.ok) return; // Not logged in or error
            const data = await res.json();
            if (data.logged_in === false) return;

            renderNotificationBell(data.unread_count, data.notifications);
        } catch (e) {
            // Silently ignore network hiccup during poll
        }
    }

    function renderNotificationBell(unreadCount, notifications) {
        let wrapper = document.getElementById('civicNotifWrapper');
        if (!wrapper) {
            wrapper = document.createElement('div');
            wrapper.id = 'civicNotifWrapper';
            wrapper.className = 'civic-notif-wrapper me-2';

            // Find best insertion target in navbar
            const dFlexActions = document.querySelector('.navbar .d-flex.align-items-center');
            const toggler = document.querySelector('.navbar .navbar-toggler');
            const msAutoNav = document.querySelector('.navbar .navbar-nav.ms-auto');
            const navbarContainer = document.querySelector('.navbar .container') || document.querySelector('.navbar');

            if (dFlexActions) {
                dFlexActions.prepend(wrapper);
            } else if (toggler && navbarContainer) {
                // Keep notification bell directly accessible on mobile outside the collapsed hamburger
                navbarContainer.insertBefore(wrapper, toggler);
            } else if (msAutoNav) {
                const navItem = document.createElement('li');
                navItem.className = 'nav-item d-flex align-items-center';
                navItem.appendChild(wrapper);
                msAutoNav.prepend(navItem);
            } else if (navbarContainer) {
                navbarContainer.appendChild(wrapper);
            } else {
                // Fallback floating top-right
                wrapper.style.cssText = 'position:fixed;top:14px;right:90px;z-index:99991;';
                document.body.appendChild(wrapper);
            }
        }

        // Render Bell Button & Drawer
        wrapper.innerHTML = `
            <button id="civicNotifBellBtn" class="civic-notif-bell-btn" title="Notifications" aria-label="Notifications">
                <i class="bi bi-bell-fill"></i>
                <span class="civic-notif-badge" id="civicNotifBadge" style="display:${unreadCount > 0 ? 'inline-block' : 'none'};">
                    ${unreadCount > 99 ? '99+' : unreadCount}
                </span>
            </button>

            <div id="civicNotifDrawer" class="civic-notif-drawer ${notifDrawerVisible ? 'show' : ''}">
                <div class="civic-notif-drawer-header">
                    <h6 class="civic-notif-drawer-title">
                        <i class="bi bi-bell-fill text-primary"></i> Notifications
                        ${unreadCount > 0 ? `<span class="badge bg-primary-subtle text-primary small">${unreadCount} new</span>` : ''}
                    </h6>
                    ${unreadCount > 0 ? `
                        <button type="button" class="btn btn-link btn-sm text-decoration-none p-0 fw-semibold" id="markAllReadBtn" style="font-size:0.75rem;">
                            Mark all read
                        </button>
                    ` : ''}
                </div>

                <div class="civic-notif-drawer-body" id="civicNotifDrawerBody">
                    ${notifications && notifications.length > 0 ? notifications.map(n => renderNotificationItem(n)).join('') : `
                        <div class="text-center py-4 text-muted small">
                            <i class="bi bi-check-circle fs-3 text-success d-block mb-1"></i>
                            No recent notifications
                        </div>
                    `}
                </div>

                <div class="civic-notif-drawer-footer">
                    <a href="/notifications">View All Notifications <i class="bi bi-arrow-right ms-1"></i></a>
                </div>
            </div>
        `;

        // Wire event listeners
        const bellBtn = document.getElementById('civicNotifBellBtn');
        const drawer = document.getElementById('civicNotifDrawer');
        if (bellBtn && drawer) {
            bellBtn.addEventListener('click', function (e) {
                e.stopPropagation();
                notifDrawerVisible = !notifDrawerVisible;
                drawer.classList.toggle('show', notifDrawerVisible);
                if (notifDrawerVisible && window.innerWidth > 576) {
                    const rect = drawer.getBoundingClientRect();
                    if (rect.left < 10) {
                        drawer.style.right = 'auto';
                        drawer.style.left = '0';
                    } else if (rect.right > window.innerWidth - 10) {
                        drawer.style.right = '0';
                        drawer.style.left = 'auto';
                    }
                }
            });
        }

        const markAllBtn = document.getElementById('markAllReadBtn');
        if (markAllBtn) {
            markAllBtn.addEventListener('click', async function (e) {
                e.stopPropagation();
                try {
                    await fetch('/api/notifications/mark_all_read', { method: 'POST' });
                    fetchNotifications();
                } catch (err) {}
            });
        }

        // Wire individual notification click to mark read
        wrapper.querySelectorAll('.civic-notif-item').forEach(item => {
            item.addEventListener('click', async function (e) {
                const notifId = this.dataset.id;
                const link = this.dataset.link;
                const isEmergency = this.dataset.emergency === 'true';
                const title = this.dataset.title;
                const message = this.dataset.message;

                try {
                    await fetch(`/api/notifications/mark_read/${notifId}`, { method: 'POST' });
                    fetchNotifications();
                } catch (err) {}

                if (isEmergency) {
                    const drawer = document.getElementById('civicNotifDrawer');
                    if (drawer) {
                        drawer.classList.remove('show');
                        notifDrawerVisible = false;
                    }
                    window.openEmergencyModal(title, message, '112 / 108 / 1800-CIVIC-ALERT', link || '/emergency/alerts');
                    return;
                }

                if (link && link !== 'null' && link !== '#') {
                    window.location.href = link;
                } else {
                    window.location.href = '/notifications';
                }
            });
        });
    }

    // Global Modal: Opens Civil Safety Emergency Directives Popup
    window.openEmergencyModal = function(title, message, helpline, link) {
        let modal = document.getElementById('civicEmergencyModal');
        if (!modal) {
            modal = document.createElement('div');
            modal.id = 'civicEmergencyModal';
            modal.className = 'modal fade';
            modal.tabIndex = -1;
            modal.innerHTML = `
                <div class="modal-dialog modal-dialog-centered modal-lg">
                    <div class="modal-content border-danger shadow-lg" style="border-width: 2px;">
                        <div class="modal-header bg-danger text-white py-3">
                            <h5 class="modal-title fw-bold d-flex align-items-center gap-2">
                                <span class="fs-4">🚨</span>
                                <span>CIVIL SAFETY EMERGENCY BROADCAST</span>
                            </h5>
                            <button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal" aria-label="Close"></button>
                        </div>
                        <div class="modal-body p-4">
                            <div class="alert alert-danger d-flex align-items-center gap-3 mb-3 py-2 px-3">
                                <i class="bi bi-shield-fill-exclamation fs-2 text-danger"></i>
                                <div>
                                    <h5 class="fw-bold mb-0 text-danger" id="civicModalAlertTitle">Emergency Title</h5>
                                    <small class="text-danger text-opacity-75">Broadcasted by Municipal Emergency Operations</small>
                                </div>
                            </div>

                            <div class="p-3 rounded-3 bg-light border mb-4">
                                <h6 class="fw-bold text-dark mb-2">
                                    <i class="bi bi-megaphone-fill text-danger me-1"></i> Public Safety Directives:
                                </h6>
                                <p class="mb-0 text-dark" id="civicModalAlertMessage" style="white-space: pre-line; line-height: 1.6; font-size: 0.95rem;"></p>
                            </div>

                            <div class="d-flex flex-wrap align-items-center justify-content-between p-3 rounded-3 border border-danger-subtle bg-danger-subtle bg-opacity-25 gap-2">
                                <div>
                                    <strong class="text-danger"><i class="bi bi-telephone-fill me-1"></i> Emergency Hotline:</strong>
                                    <span class="ms-2 fw-bold text-dark fs-5" id="civicModalAlertHelpline">112</span>
                                </div>
                                <a href="tel:112" id="civicModalHelplineBtn" class="btn btn-danger fw-bold rounded-pill px-3 shadow-sm">
                                    <i class="bi bi-telephone-outbound-fill me-1"></i> Call Hotline Now
                                </a>
                            </div>
                        </div>
                        <div class="modal-footer bg-light py-2 px-4 justify-content-between">
                            <a href="/emergency/alerts" id="civicModalCrisisHubBtn" class="btn btn-outline-danger fw-semibold">
                                <i class="bi bi-shield-check me-1"></i> Open Full Crisis Hub
                            </a>
                            <button type="button" class="btn btn-secondary px-4 fw-bold" data-bs-dismiss="modal">
                                Acknowledge & Close
                            </button>
                        </div>
                    </div>
                </div>
            `;
            document.body.appendChild(modal);
        }

        const titleEl = document.getElementById('civicModalAlertTitle');
        const msgEl = document.getElementById('civicModalAlertMessage');
        const hlEl = document.getElementById('civicModalAlertHelpline');
        const hlBtn = document.getElementById('civicModalHelplineBtn');
        const hubBtn = document.getElementById('civicModalCrisisHubBtn');

        if (titleEl) titleEl.textContent = title || 'Civil Emergency Alert';
        if (msgEl) msgEl.textContent = message || 'Please take precautions and follow civil defense directives.';
        const hl = helpline || '112 / 108 / 1800-CIVIC-ALERT';
        if (hlEl) hlEl.textContent = hl;
        if (hlBtn) {
            const phone = hl.split('/')[0].trim();
            hlBtn.href = 'tel:' + phone;
        }
        if (hubBtn && link) {
            hubBtn.href = link;
        }

        // Explicitly suppress floating emergency docked pill while modal is open
        const dockedPill = document.getElementById('civicEmergencyDockedPill');
        if (dockedPill) {
            dockedPill.style.display = 'none';
        }

        modal.addEventListener('hidden.bs.modal', function () {
            const activeDockedPill = document.getElementById('civicEmergencyDockedPill');
            const banner = document.getElementById('civicEmergencyBanner');
            if (activeDockedPill && (!banner || banner.style.display === 'none')) {
                activeDockedPill.style.display = 'flex';
            }
        }, { once: true });

        if (window.bootstrap && window.bootstrap.Modal) {
            const bsModal = bootstrap.Modal.getInstance(modal) || new bootstrap.Modal(modal);
            bsModal.show();
        } else {
            modal.classList.add('show');
            modal.style.display = 'block';
        }
    };

    function renderNotificationItem(n) {
        let iconClass = 'bi-bell-fill';
        let iconBg = 'bg-primary-subtle text-primary';

        if (n.is_emergency) {
            iconClass = 'bi-shield-fill-exclamation';
            iconBg = 'bg-danger text-white';
        } else if (n.category === 'ticket_update') {
            iconClass = 'bi-ticket-detailed-fill';
            iconBg = 'bg-primary-subtle text-primary';
        } else if (n.category === 'volunteer') {
            iconClass = 'bi-people-fill';
            iconBg = 'bg-success-subtle text-success';
        } else if (n.category === 'donation') {
            iconClass = 'bi-heart-fill';
            iconBg = 'bg-info-subtle text-info';
        }

        return `
            <div class="civic-notif-item ${!n.is_read ? 'unread' : ''} ${n.is_emergency ? 'is-emergency' : ''}"
                 data-id="${n.id}"
                 data-link="${n.link || '/emergency/alerts'}"
                 data-emergency="${n.is_emergency ? 'true' : 'false'}"
                 data-title="${escapeHtml(n.title)}"
                 data-message="${escapeHtml(n.message)}">
                <div class="civic-notif-item-icon ${iconBg}">
                    <i class="bi ${iconClass}"></i>
                </div>
                <div class="civic-notif-item-content">
                    <div class="civic-notif-item-title">
                        <span>${escapeHtml(n.title)}</span>
                        ${n.is_emergency ? '<span class="badge bg-danger text-white" style="font-size:0.65rem;">SOS</span>' : ''}
                    </div>
                    <div class="civic-notif-item-text">${escapeHtml(n.message)}</div>
                    <div class="civic-notif-item-time"><i class="bi bi-clock me-1"></i>${n.time_ago}</div>
                </div>
            </div>
        `;
    }

    // ==========================================================================
    // Site-Wide Emergency Broadcast & Disaster SOS System
    // ==========================================================================
    function initEmergencyBroadcastSystem() {
        checkActiveEmergency();
        setInterval(checkActiveEmergency, 25000);
    }

    async function checkActiveEmergency() {
        try {
            const res = await fetch('/api/emergency/active');
            if (!res.ok) return;
            const data = await res.json();

            if (data.active) {
                renderEmergencyAlert(data);
            } else {
                removeEmergencyAlert();
            }
        } catch (e) {
            // Silently ignore polling network error
        }
    }

    function renderEmergencyAlert(alert) {
        const isDismissed = sessionStorage.getItem('civic_emergency_dismissed_' + alert.id) === 'true';

        let banner = document.getElementById('civicEmergencyBanner');
        let dockedPill = document.getElementById('civicEmergencyDockedPill');

        if (isDismissed) {
            if (banner) banner.style.display = 'none';

            // Show docked SOS pill
            if (!dockedPill) {
                dockedPill = document.createElement('div');
                dockedPill.id = 'civicEmergencyDockedPill';
                dockedPill.className = 'civic-emergency-docked-pill';
                document.body.appendChild(dockedPill);
            }
            dockedPill.style.display = 'flex';
            dockedPill.innerHTML = `
                <i class="bi bi-exclamation-triangle-fill"></i>
                <span>🚨 Active Emergency: ${escapeHtml(alert.title)}</span>
            `;
            dockedPill.onclick = function () {
                sessionStorage.removeItem('civic_emergency_dismissed_' + alert.id);
                dockedPill.style.display = 'none';
                if (banner) banner.style.display = 'block';
                else renderEmergencyAlert(alert);
            };
            return;
        }

        // If not dismissed, render or update banner
        if (dockedPill) dockedPill.style.display = 'none';

        if (!banner) {
            banner = document.createElement('div');
            banner.id = 'civicEmergencyBanner';
            banner.className = 'civic-emergency-banner';
            document.body.prepend(banner);
        }

        banner.style.display = 'block';
        banner.innerHTML = `
            <div class="civic-emergency-content">
                <div class="civic-emergency-siren-box">
                    <span class="civic-emergency-siren-icon">🚨</span>
                    <div>
                        <div class="d-flex align-items-center gap-2">
                            <span class="civic-emergency-badge">${escapeHtml(alert.severity)}</span>
                            <h6 class="civic-emergency-title">${escapeHtml(alert.title)}</h6>
                        </div>
                    </div>
                </div>

                <div class="civic-emergency-actions">
                    <a href="tel:${alert.helpline.split('/')[0].trim()}" class="civic-emergency-helpline-btn">
                        <i class="bi bi-telephone-fill"></i> Helpline: ${escapeHtml(alert.helpline)}
                    </a>
                    <button class="civic-emergency-expand-btn" id="civicEmergencyExpandBtn">
                        <i class="bi bi-info-circle me-1"></i> Directives
                    </button>
                    <button class="civic-emergency-collapse-btn" id="civicEmergencyCollapseBtn" title="Collapse alert">
                        <i class="bi bi-x-lg"></i>
                    </button>
                </div>

                <div class="civic-emergency-details-panel" id="civicEmergencyDetailsPanel">
                    <strong><i class="bi bi-shield-exclamation me-1"></i> Public Directives:</strong>
                    ${escapeHtml(alert.message)}
                </div>
            </div>
        `;

        // Directives expansion toggle
        const expandBtn = document.getElementById('civicEmergencyExpandBtn');
        const detailsPanel = document.getElementById('civicEmergencyDetailsPanel');
        if (expandBtn && detailsPanel) {
            expandBtn.addEventListener('click', function () {
                detailsPanel.classList.toggle('show');
                expandBtn.innerHTML = detailsPanel.classList.contains('show')
                    ? '<i class="bi bi-chevron-up me-1"></i> Hide Directives'
                    : '<i class="bi bi-info-circle me-1"></i> Directives';
            });
        }

        // Collapse button
        const collapseBtn = document.getElementById('civicEmergencyCollapseBtn');
        if (collapseBtn) {
            collapseBtn.addEventListener('click', function () {
                sessionStorage.setItem('civic_emergency_dismissed_' + alert.id, 'true');
                renderEmergencyAlert(alert);
            });
        }
    }

    function removeEmergencyAlert() {
        const banner = document.getElementById('civicEmergencyBanner');
        if (banner) banner.remove();
        const dockedPill = document.getElementById('civicEmergencyDockedPill');
        if (dockedPill) dockedPill.remove();
    }

    function escapeHtml(str) {
        if (!str) return '';
        const d = document.createElement('div');
        d.textContent = str;
        return d.innerHTML;
    }

    // Auto-dismiss alert notifications after 5 seconds
    function initAlertAutoDismiss() {
        const alerts = document.querySelectorAll('.alert:not(.alert-permanent)');
        alerts.forEach(function (alert) {
            setTimeout(function () {
                const closeBtn = alert.querySelector('.btn-close');
                if (closeBtn) {
                    closeBtn.click();
                } else {
                    alert.style.transition = 'opacity 0.5s ease';
                    alert.style.opacity = '0';
                    setTimeout(() => alert.remove(), 500);
                }
            }, 5000);
        });
    }

    // Global helper: Show transient toast notification
    window.showCivicToast = function (message, type = 'info') {
        const toastContainer = document.getElementById('civic-toast-container') || (function () {
            const container = document.createElement('div');
            container.id = 'civic-toast-container';
            container.style.cssText = 'position:fixed;top:20px;right:20px;z-index:99999;min-width:280px;';
            document.body.appendChild(container);
            return container;
        })();

        const toast = document.createElement('div');
        toast.className = `alert alert-${type} shadow-lg py-2 px-3 mb-2 rounded-3 d-flex align-items-center justify-content-between`;
        toast.innerHTML = `
            <div>${message}</div>
            <button type="button" class="btn-close ms-2" onclick="this.parentElement.remove()"></button>
        `;
        toastContainer.appendChild(toast);

        setTimeout(() => {
            toast.style.opacity = '0';
            setTimeout(() => toast.remove(), 400);
        }, 4000);
    };

    window.toggleCivicTheme = toggleTheme;
})();
