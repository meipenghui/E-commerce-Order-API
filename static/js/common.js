"use strict";

const TOKEN_KEY = "ecommerce_access_token";

class ApiError extends Error {
    constructor(message, status = 0, payload = null) {
        super(message);
        this.name = "ApiError";
        this.status = status;
        this.payload = payload;
    }
}

function getToken() {
    return window.localStorage.getItem(TOKEN_KEY);
}

function setToken(token) {
    window.localStorage.setItem(TOKEN_KEY, token);
}

function clearToken() {
    window.localStorage.removeItem(TOKEN_KEY);
}

function getSafeNextUrl() {
    const next = new URLSearchParams(window.location.search).get("next");
    if (next && next.startsWith("/") && !next.startsWith("//")) {
        return next;
    }
    return "/products";
}

function redirectToLogin() {
    if (window.location.pathname === "/login") {
        return;
    }
    const next = encodeURIComponent(`${window.location.pathname}${window.location.search}`);
    window.location.assign(`/login?next=${next}`);
}

function logout() {
    clearToken();
    window.location.assign("/login");
}

function extractErrorMessage(payload) {
    if (!payload) {
        return "";
    }
    if (typeof payload === "string") {
        return payload;
    }
    if (typeof payload.detail === "string") {
        return payload.detail;
    }
    if (Array.isArray(payload.detail)) {
        return payload.detail
            .map((item) => {
                const location = Array.isArray(item.loc) ? item.loc.slice(1).join(".") : "";
                return location ? `${location}: ${item.msg}` : item.msg;
            })
            .filter(Boolean)
            .join("；");
    }
    if (typeof payload.message === "string") {
        return payload.message;
    }
    return "";
}

async function fetchApi(url, options = {}) {
    const {
        auth = true,
        headers: suppliedHeaders,
        ...requestOptions
    } = options;
    const headers = new Headers(suppliedHeaders || {});
    const token = getToken();

    if (auth && token && !headers.has("Authorization")) {
        headers.set("Authorization", `Bearer ${token}`);
    }

    let response;
    try {
        response = await fetch(url, {
            ...requestOptions,
            headers,
        });
    } catch (error) {
        throw new ApiError("网络连接失败，请检查服务是否已启动", 0, null);
    }

    const responseText = await response.text();
    let payload = null;
    if (responseText) {
        try {
            payload = JSON.parse(responseText);
        } catch (error) {
            payload = responseText;
        }
    }

    if (!response.ok) {
        const error = new ApiError(
            extractErrorMessage(payload) || `请求失败（HTTP ${response.status}）`,
            response.status,
            payload,
        );
        if (response.status === 401 && auth) {
            clearToken();
            redirectToLogin();
        }
        throw error;
    }

    return payload;
}

function showToast(message, type = "success") {
    const root = document.getElementById("toast-root");
    if (!root) {
        return;
    }

    const icons = {
        success: "✓",
        error: "!",
        info: "i",
    };
    const toast = document.createElement("div");
    toast.className = `toast toast-${type}`;
    toast.setAttribute("role", type === "error" ? "alert" : "status");

    const icon = document.createElement("span");
    icon.className = "toast-icon";
    icon.textContent = icons[type] || icons.info;

    const text = document.createElement("span");
    text.className = "flex-1";
    text.textContent = message;

    toast.append(icon, text);
    root.append(toast);
    window.requestAnimationFrame(() => toast.classList.add("toast-visible"));

    window.setTimeout(() => {
        toast.classList.remove("toast-visible");
        window.setTimeout(() => toast.remove(), 220);
    }, 3400);
}

function escapeHtml(value) {
    const replacements = {
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#039;",
    };
    return String(value ?? "").replace(/[&<>"']/g, (character) => replacements[character]);
}

function formatMoney(value) {
    const amount = Number(value ?? 0);
    if (!Number.isFinite(amount)) {
        return "¥0.00";
    }
    return new Intl.NumberFormat("zh-CN", {
        style: "currency",
        currency: "CNY",
        minimumFractionDigits: 2,
    }).format(amount);
}

function formatDate(value) {
    if (!value) {
        return "-";
    }
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) {
        return "-";
    }
    return new Intl.DateTimeFormat("zh-CN", {
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
    }).format(date);
}

function createUuid() {
    if (window.crypto && typeof window.crypto.randomUUID === "function") {
        return window.crypto.randomUUID();
    }
    return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (character) => {
        const random = Math.floor(Math.random() * 16);
        const value = character === "x" ? random : (random & 0x3) | 0x8;
        return value.toString(16);
    });
}

function setButtonBusy(button, busy, busyText = "处理中...") {
    if (!button) {
        return;
    }
    if (busy) {
        button.dataset.idleText = button.textContent;
        button.textContent = busyText;
        button.disabled = true;
        return;
    }
    if (button.dataset.idleText) {
        button.textContent = button.dataset.idleText;
        delete button.dataset.idleText;
    }
    button.disabled = false;
}

function initNavigation() {
    document.querySelectorAll("[data-nav]").forEach((link) => {
        const name = link.dataset.nav;
        const active = (name === "products" && window.location.pathname.startsWith("/products"))
            || (name === "orders" && window.location.pathname.startsWith("/orders"));
        link.classList.toggle("active", active);
    });

    const authRoot = document.getElementById("nav-auth");
    if (authRoot) {
        authRoot.replaceChildren();
        if (getToken()) {
            const button = document.createElement("button");
            button.type = "button";
            button.dataset.action = "logout";
            button.className = "btn-secondary !px-3 !py-1.5 text-xs";
            button.textContent = "退出登录";
            authRoot.append(button);
        } else {
            const link = document.createElement("a");
            link.href = "/login";
            link.className = "btn-primary !px-3 !py-1.5 text-xs";
            link.textContent = "登录";
            authRoot.append(link);
        }
    }
}

document.addEventListener("click", (event) => {
    const logoutButton = event.target.closest("[data-action='logout']");
    if (logoutButton) {
        event.preventDefault();
        logout();
    }
});

document.addEventListener("DOMContentLoaded", initNavigation);
