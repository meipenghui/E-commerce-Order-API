"use strict";

document.addEventListener("DOMContentLoaded", () => {
    const grid = document.getElementById("products-grid");
    const loading = document.getElementById("products-loading");
    const empty = document.getElementById("products-empty");
    const errorPanel = document.getElementById("products-error");
    const errorMessage = document.getElementById("products-error-message");
    const summary = document.getElementById("products-summary");
    const refreshButton = document.getElementById("refresh-products");

    if (!grid || !loading || !empty || !errorPanel) {
        return;
    }

    refreshButton.addEventListener("click", () => loadProducts());

    grid.addEventListener("click", async (event) => {
        const buyButton = event.target.closest("[data-action='buy-sku']");
        if (!buyButton || buyButton.disabled) {
            return;
        }

        if (!getToken()) {
            showToast("请先登录后再购买", "info");
            redirectToLogin();
            return;
        }

        const skuRow = buyButton.closest("[data-sku-row]");
        const quantityInput = skuRow ? skuRow.querySelector("[data-quantity-for]") : null;
        const maxQuantity = Number(quantityInput?.max || 1);
        const requestedQuantity = Number.parseInt(quantityInput?.value || "1", 10);
        const quantity = Math.min(Math.max(requestedQuantity || 1, 1), Math.max(maxQuantity, 1));
        const skuId = Number(buyButton.dataset.skuId);
        let succeeded = false;

        setButtonBusy(buyButton, true, "下单中...");
        try {
            const order = await fetchApi("/api/v1/orders/", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    "X-Idempotency-Key": createUuid(),
                },
                body: JSON.stringify({
                    items: [{ sku_id: skuId, quantity }],
                }),
            });
            succeeded = true;
            showToast(`下单成功：${order.order_no}`);
            window.setTimeout(() => window.location.assign("/orders"), 700);
        } catch (error) {
            showToast(error.message || "下单失败，请稍后重试", "error");
        } finally {
            if (!succeeded) {
                setButtonBusy(buyButton, false);
            }
        }
    });

    document.addEventListener("click", async (event) => {
        if (event.target.closest("[data-action='retry-products']")) {
            await loadProducts();
        }
    });

    async function loadProducts() {
        showLoadingState();
        if (refreshButton) {
            refreshButton.disabled = true;
        }

        try {
            const products = await fetchApi("/api/v1/products/?page=1&page_size=100", {
                auth: false,
            });
            renderProducts(Array.isArray(products) ? products : []);
        } catch (error) {
            showErrorState(error.message || "无法获取商品数据");
        } finally {
            if (refreshButton) {
                refreshButton.disabled = false;
            }
        }
    }

    function showLoadingState() {
        loading.classList.remove("hidden");
        grid.classList.add("hidden");
        empty.classList.add("hidden");
        errorPanel.classList.add("hidden");
        if (summary) {
            summary.classList.add("hidden");
        }
    }

    function showErrorState(message) {
        loading.classList.add("hidden");
        grid.classList.add("hidden");
        empty.classList.add("hidden");
        errorPanel.classList.remove("hidden");
        if (errorMessage) {
            errorMessage.textContent = message;
        }
        if (summary) {
            summary.classList.add("hidden");
        }
    }

    function renderProducts(products) {
        loading.classList.add("hidden");
        errorPanel.classList.add("hidden");

        if (!products.length) {
            empty.classList.remove("hidden");
            grid.classList.add("hidden");
            if (summary) {
                summary.classList.add("hidden");
            }
            return;
        }

        empty.classList.add("hidden");
        grid.classList.remove("hidden");
        grid.innerHTML = products.map(renderProductCard).join("");

        const skuCount = products.reduce((total, product) => total + (product.skus?.length || 0), 0);
        if (summary) {
            summary.textContent = `当前展示 ${products.length} 件商品，共 ${skuCount} 个 SKU。库存以服务端最新数据为准。`;
            summary.classList.remove("hidden");
        }
    }

    function renderProductCard(product) {
        const productActive = Boolean(product.is_active);
        const skus = Array.isArray(product.skus) ? product.skus : [];
        const description = product.description || "暂无商品描述";
        const statusBadge = productActive
            ? '<span class="rounded-full bg-emerald-50 px-2.5 py-1 text-xs font-medium text-emerald-700 ring-1 ring-inset ring-emerald-200">在售</span>'
            : '<span class="rounded-full bg-slate-100 px-2.5 py-1 text-xs font-medium text-slate-600 ring-1 ring-inset ring-slate-200">已下架</span>';

        return `
            <article class="product-card flex h-full flex-col rounded-3xl border border-slate-200 bg-white p-6 shadow-soft">
                <div class="flex items-start justify-between gap-4">
                    <div class="min-w-0">
                        <div class="flex flex-wrap items-center gap-2">
                            ${statusBadge}
                            <span class="rounded-full bg-brand-50 px-2.5 py-1 text-xs font-medium text-brand-700">${skus.length} 个 SKU</span>
                        </div>
                        <h2 class="mt-4 text-xl font-bold tracking-tight text-slate-900">${escapeHtml(product.name)}</h2>
                        <p class="line-clamp-2 mt-2 text-sm leading-6 text-slate-500">${escapeHtml(description)}</p>
                    </div>
                </div>

                <div class="mt-6 flex-1 space-y-3">
                    ${skus.length ? skus.map((sku) => renderSku(productActive, sku)).join("") : '<div class="rounded-2xl border border-dashed border-slate-200 px-4 py-8 text-center text-sm text-slate-400">该商品暂未配置 SKU</div>'}
                </div>
            </article>
        `;
    }

    function renderSku(productActive, sku) {
        const stock = Number(sku.available_stock || 0);
        const lockedStock = Number(sku.locked_stock || 0);
        const unavailable = !productActive || stock <= 0;
        const quantityMax = Math.max(stock, 1);
        const buttonText = !productActive ? "商品已下架" : (stock <= 0 ? "已售罄" : "立即购买");

        return `
            <div data-sku-row data-sku-id="${sku.id}" class="rounded-2xl border border-slate-200 bg-slate-50/80 p-4">
                <div class="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
                    <div class="min-w-0">
                        <div class="flex flex-wrap items-center gap-x-3 gap-y-1">
                            <span class="truncate text-sm font-semibold text-slate-900">${escapeHtml(sku.sku_code)}</span>
                            <span class="text-base font-bold text-brand-700">${formatMoney(sku.price)}</span>
                        </div>
                        <div class="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-500">
                            <span>可用库存 <strong class="font-semibold text-slate-700">${stock}</strong></span>
                            <span>锁定库存 <strong class="font-semibold text-slate-700">${lockedStock}</strong></span>
                        </div>
                    </div>

                    <div class="flex items-center gap-2">
                        <label class="sr-only" for="quantity-${sku.id}">购买数量</label>
                        <input id="quantity-${sku.id}" data-quantity-for="${sku.id}" type="number" min="1" max="${quantityMax}" step="1" value="1" ${unavailable ? "disabled" : ""} class="form-input !w-20 !py-2 text-center">
                        <button type="button" data-action="buy-sku" data-sku-id="${sku.id}" ${unavailable ? "disabled" : ""} class="btn-primary !py-2 text-xs">
                            ${buttonText}
                        </button>
                    </div>
                </div>
            </div>
        `;
    }

    loadProducts();
});
