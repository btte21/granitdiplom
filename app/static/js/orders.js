document.addEventListener("DOMContentLoaded", () => {
    const addButton = document.getElementById("add-item-btn");
    const itemsInput = document.getElementById("items_json");
    const itemsList = document.getElementById("order-items-list");
    const productSelector = document.getElementById("product_selector");
    const quantityInput = document.getElementById("item_quantity");

    if (!addButton || !itemsInput || !itemsList || !productSelector || !quantityInput) {
        return;
    }

    let items = [];

    const renderItems = () => {
        itemsInput.value = JSON.stringify(items);
        if (!items.length) {
            itemsList.innerHTML = '<div class="empty-state">No items added yet.</div>';
            return;
        }

        itemsList.innerHTML = items
            .map(
                (item, index) => `
                    <div class="d-flex justify-content-between align-items-center border rounded-4 px-3 py-2">
                        <div>
                            <div class="fw-semibold">${item.name}</div>
                            <div class="text-secondary">Product ID ${item.product_id} | Qty ${item.quantity}</div>
                        </div>
                        <button class="btn btn-sm btn-outline-danger" type="button" data-remove-index="${index}">Remove</button>
                    </div>
                `
            )
            .join("");

        itemsList.querySelectorAll("[data-remove-index]").forEach((button) => {
            button.addEventListener("click", () => {
                items.splice(Number(button.dataset.removeIndex), 1);
                renderItems();
            });
        });
    };

    addButton.addEventListener("click", () => {
        const option = productSelector.options[productSelector.selectedIndex];
        const productId = Number(option.value);
        const quantity = Number(quantityInput.value);
        if (!productId || quantity < 1) {
            return;
        }

        items.push({
            product_id: productId,
            quantity,
            name: option.dataset.name,
        });
        renderItems();
    });
});
