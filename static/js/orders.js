"use strict";

document.addEventListener("DOMContentLoaded", () => {
    const list = document.getElementById("orders-list");
    const loading = document.getElementById("orders-loading");
    const empty = document.getElementById("orders-empty");
    const errorPanel = document.getElementById("orders-error");
    const errorMessage = document.getElementById("orders-error-message");
    const summary = document.getElementById("orders-summary");
    const refreshButton = document.getElementById("refresh-orders");

    if (!list || !loading || !empty || !errorPanel) {
        return;
    }

    if (!getToken()) {
        redirectToLogin();
        return;
    }

    const statusMeta = {
        PENDING_PAYMENT: {
            label: "待支付",
            className: "bg-amber-50 text-amber-700 ring-amber-200",
            dot: "bg-amber-500",
        },
        PAID: {
            label: "已支付",
            className: "bg-emerald-50 text-emerald-700 ring-emerald-200",
            dot: "bg-emerald-500",
        },
        CANCELLED: {
            label: "已取消",
            className: "bg-slate-100 text-slate-600 ring-slate-200",
            dot: "bg-slate-400",
        },
        SHIPPED: {
            label: "已发货",
            className: "bg-blue-50 text-blue-700 ring-blue-200",
            dot: "bg-blue-500",
        },
        COMPLETED: {
            label: "已完成",
            className: "bg-teal-50 text-teal-700 ring-teal-200",
            dot: "bg-teal-500",
        },
    };

    refreshButton.addEventListener("click", () => loadOrders());

    list.addEventListener("click", async (event) => {
        const payButton = event.target.closest("[data-action='pay-order']");
        if (payButton) {
            await payOrder(payButton.dataset.orderNo, payButton);
            return;
        }

        const cancelButton = event.target.closest("[data-action='cancel-order']");
        if (cancelButton) {
            await cancelOrder(cancelButton.dataset.orderNo, cancelButton);
        }
    });

    document.addEventListener("click", async (event) => {
        if (event.target.closest("[data-action='retry-orders']")) {
            await loadOrders();
        }
    });

    async function loadOrders() {
        showLoadingState();
        if (refreshButton) {
            refreshButton.disabled = true;
        }

        try {
            const orders = await fetchApi("/api/v1/orders/");
            renderOrders(Array.isArray(orders) ? orders : []);
        } catch (error) {
            if (error.status !== 401) {
                showErrorState(error.message || "无法获取订单数据");
            }
        } finally {
            if (refreshButton) {
                refreshButton.disabled = false;
            }
        }
    }

    function showLoadingState() {
        loading.classList.remove("hidden");
        list.classList.add("hidden");
        empty.classList.add("hidden");
        errorPanel.classList.add("hidden");
        if (summary) {
            summary.classList.add("hidden");
        }
    }

    function showErrorState(message) {
        loading.classList.add("hidden");
        list.classList.add("hidden");
        empty.classList.add("hidden");
        errorPanel.classList.remove("hidden");
        if (errorMessage) {
            errorMessage.textContent = message;
        }
        if (summary) {
            summary.classList.add("hidden");
        }
    }

    function renderOrders(orders) {
        loading.classList.add("hidden");
        errorPanel.classList.add("hidden");

        if (!orders.length) {
            list.classList.add("hidden");
            empty.classList.remove("hidden");
            if (summary) {
                summary.classList.add("hidden");
            }
            return;
        }

        empty.classList.add("hidden");
        list.classList.remove("hidden");
        list.innerHTML = orders.map(renderOrderCard).join("");

        if (summary) {
            const pendingCount = orders.filter((order) => order.status === "PENDING_PAYMENT").length;
            const paidCount = orders.filter((order) => order.status === "PAID").length;
            summary.textContent = `共 ${orders.length} 笔订单，待支付 ${pendingCount} 笔，已支付 ${paidCount} 笔。`;
            summary.classList.remove("hidden");
        }
    }

    function renderOrderCard(order) {
        const meta = statusMeta[order.status] || {
            label: order.status,
            className: "bg-slate-100 text-slate-600 ring-slate-200",
            dot: "bg-slate-400",
        };
        const items = Array.isArray(order.items) ? order.items : [];
        const pending = order.status === "PENDING_PAYMENT";
        const itemCount = items.reduce((total, item) => total + Number(item.quantity || 0), 0);

        return `
            <article class="order-card rounded-3xl border border-slate-200 bg-white p-5 shadow-soft sm:p-6">
                <div class="flex flex-col gap-5 sm:flex-row sm:items-start sm:justify-between">
                    <div class="min-w-0">
                        <div class="flex flex-wrap items-center gap-2.5">
                            <span class="inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold ring-1 ring-inset ${meta.className}">
                                <span class="h-1.5 w-1.5 rounded-full ${meta.dot}"></span>
                                ${escapeHtml(meta.label)}
                            </span>
                            <span class="text-xs text-slate-400">订单号</span>
                        </div>
                        <h2 class="mt-2 break-all text-base font-bold tracking-wide text-slate-900">${escapeHtml(order.order_no)}</h2>
                        <p class="mt-1 text-xs text-slate-500">创建时间：${escapeHtml(formatDate(order.created_at))}</p>
                    </div>
                    <div class="rounded-2xl bg-slate-50 px-4 py-3 sm:text-right">
                        <p class="text-xs text-slate-500">订单金额</p>
                        <p class="mt-1 text-xl font-bold text-brand-700">${formatMoney(order.total_amount)}</p>
                    </div>
                </div>

                <div class="mt-5 overflow-hidden rounded-2xl border border-slate-200">
                    <div class="hidden bg-slate-50 px-4 py-2.5 text-xs font-medium text-slate-500 sm:grid sm:grid-cols-[1fr_80px_120px_120px] sm:gap-4">
                        <span>SKU</span>
                        <span class="text-center">数量</span>
                        <span class="text-right">单价</span>
                        <span class="text-right">小计</span>
                    </div>
                    <div class="divide-y divide-slate-100">
                        ${items.map(renderOrderItem).join("") || '<div class="px-4 py-5 text-sm text-slate-400">订单明细为空</div>'}
                    </div>
                </div>

                <div class="mt-5 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                    <p class="text-xs text-slate-500">共 ${itemCount} 件商品${pending ? " · 未支付订单将由系统自动取消" : ""}</p>
                    ${pending ? `
                        <div class="flex gap-2">
                            <button type="button" data-action="pay-order" data-order-no="${escapeHtml(order.order_no)}" class="btn-primary !py-2 text-xs">去支付</button>
                            <button type="button" data-action="cancel-order" data-order-no="${escapeHtml(order.order_no)}" class="btn-secondary !py-2 text-xs">取消订单</button>
                        </div>
                    ` : ""}
                </div>
            </article>
        `;
    }

    function renderOrderItem(item) {
        return `
            <div class="grid gap-2 px-4 py-3.5 text-sm sm:grid-cols-[1fr_80px_120px_120px] sm:items-center sm:gap-4">
                <div>
                    <span class="font-medium text-slate-800">SKU #${escapeHtml(item.sku_id)}</span>
                    <span class="ml-2 text-xs text-slate-400 sm:hidden">单价 ${formatMoney(item.unit_price)}</span>
                </div>
                <div class="text-xs text-slate-500 sm:text-center">× ${escapeHtml(item.quantity)}</div>
                <div class="hidden text-right text-slate-600 sm:block">${formatMoney(item.unit_price)}</div>
                <div class="text-left font-semibold text-slate-800 sm:text-right">${formatMoney(item.subtotal)}</div>
            </div>
        `;
    }

    async function payOrder(orderNo, button) {
        if (!orderNo || !window.confirm(`确认模拟支付订单 ${orderNo}？`)) {
            return;
        }

        setButtonBusy(button, true, "支付中...");
        try {
            const result = await fetchApi("/api/v1/payments/callback", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                },
                body: JSON.stringify({
                    order_no: orderNo,
                    status: "SUCCESS",
                }),
            });
            showToast(result.duplicate ? "订单已支付，无需重复操作" : "支付成功");
            await loadOrders();
        } catch (error) {
            if (error.status !== 401) {
                showToast(error.message || "支付失败，请稍后重试", "error");
            }
        } finally {
            setButtonBusy(button, false);
        }
    }

    async function cancelOrder(orderNo, button) {
        if (!orderNo || !window.confirm(`确认取消订单 ${orderNo}？库存将被释放。`)) {
            return;
        }

        setButtonBusy(button, true, "取消中...");
        try {
            await fetchApi(`/api/v1/orders/${encodeURIComponent(orderNo)}`, {
                method: "DELETE",
            });
            showToast("订单已取消，库存已释放");
            await loadOrders();
        } catch (error) {
            if (error.status !== 401) {
                showToast(error.message || "取消订单失败，请稍后重试", "error");
            }
        } finally {
            setButtonBusy(button, false);
        }
    }

    loadOrders();
});
