"use strict";

document.addEventListener("DOMContentLoaded", () => {
    const loginForm = document.getElementById("login-form");
    const registerForm = document.getElementById("register-form");
    const loginSubmit = document.getElementById("login-submit");
    const registerSubmit = document.getElementById("register-submit");
    const messageBox = document.getElementById("auth-message");
    const tabButtons = Array.from(document.querySelectorAll("[data-tab-button]"));

    if (!loginForm || !registerForm) {
        return;
    }

    redirectIfAlreadyLoggedIn();

    function setMode(mode) {
        const isLogin = mode === "login";
        loginForm.classList.toggle("hidden", !isLogin);
        registerForm.classList.toggle("hidden", isLogin);

        tabButtons.forEach((button) => {
            const active = button.dataset.tabButton === mode;
            button.setAttribute("aria-selected", String(active));
            button.className = active
                ? "rounded-lg bg-white px-4 py-2 text-sm font-semibold text-slate-900 shadow-sm"
                : "rounded-lg px-4 py-2 text-sm font-semibold text-slate-500 transition hover:text-slate-800";
        });

        clearMessage();
        const firstInput = (isLogin ? loginForm : registerForm).querySelector("input");
        if (firstInput) {
            window.setTimeout(() => firstInput.focus(), 50);
        }
    }

    function clearMessage() {
        if (messageBox) {
            messageBox.classList.add("hidden");
            messageBox.textContent = "";
        }
    }

    function showMessage(message, type = "error") {
        if (!messageBox) {
            return;
        }
        const classes = type === "success"
            ? "border-emerald-200 bg-emerald-50 text-emerald-800"
            : "border-rose-200 bg-rose-50 text-rose-700";
        messageBox.className = `mb-4 rounded-xl border px-4 py-3 text-sm ${classes}`;
        messageBox.textContent = message;
    }

    async function loginWithCredentials(username, password) {
        const payload = await fetchApi("/api/v1/login", {
            method: "POST",
            auth: false,
            headers: {
                "Content-Type": "application/x-www-form-urlencoded",
            },
            body: new URLSearchParams({ username, password }).toString(),
        });
        setToken(payload.access_token);
    }

    tabButtons.forEach((button) => {
        button.addEventListener("click", () => setMode(button.dataset.tabButton));
    });

    loginForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        clearMessage();
        if (!loginForm.reportValidity()) {
            return;
        }

        const username = document.getElementById("login-username").value.trim();
        const password = document.getElementById("login-password").value;

        setButtonBusy(loginSubmit, true, "登录中...");
        try {
            await loginWithCredentials(username, password);
            showToast("登录成功，正在进入商品列表");
            showMessage("登录成功，正在跳转...", "success");
            window.setTimeout(() => window.location.assign(getSafeNextUrl()), 450);
        } catch (error) {
            const message = error.message || "登录失败，请检查用户名和密码";
            showMessage(message);
            showToast(message, "error");
        } finally {
            setButtonBusy(loginSubmit, false);
        }
    });

    registerForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        clearMessage();
        if (!registerForm.reportValidity()) {
            return;
        }

        const username = document.getElementById("register-username").value.trim();
        const email = document.getElementById("register-email").value.trim();
        const password = document.getElementById("register-password").value;
        const confirmPassword = document.getElementById("register-confirm").value;

        if (password !== confirmPassword) {
            showMessage("两次输入的密码不一致");
            showToast("两次输入的密码不一致", "error");
            return;
        }

        setButtonBusy(registerSubmit, true, "注册中...");
        try {
            await fetchApi("/api/v1/register", {
                method: "POST",
                auth: false,
                headers: {
                    "Content-Type": "application/json",
                },
                body: JSON.stringify({ username, email, password }),
            });
            await loginWithCredentials(username, password);
            showToast("注册成功，已自动登录");
            showMessage("注册成功，正在进入商品列表...", "success");
            window.setTimeout(() => window.location.assign(getSafeNextUrl()), 500);
        } catch (error) {
            const message = error.message || "注册失败，请稍后重试";
            showMessage(message);
            showToast(message, "error");
        } finally {
            setButtonBusy(registerSubmit, false);
        }
    });

    async function redirectIfAlreadyLoggedIn() {
        const token = getToken();
        if (!token) {
            return;
        }
        try {
            const response = await fetch("/api/v1/me", {
                headers: {
                    Authorization: `Bearer ${token}`,
                },
            });
            if (response.ok) {
                window.location.replace(getSafeNextUrl());
                return;
            }
            clearToken();
        } catch (error) {
            clearToken();
        }
    }
});
