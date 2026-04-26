class ProductCreationUI {
  constructor() {
    this.featuredLimit = 3;
    this.template = document.getElementById("productCardTemplate");
    this.productList = document.getElementById("productList");
    this.addButton = document.getElementById("addProductButton");
    this.cancelButton = document.getElementById("cancelButton");
    this.form = document.getElementById("productForm");
    this.counter = document.getElementById("featuredCounter");
    this.warningBanner = document.getElementById("featuredWarning");
    this.toast = document.getElementById("toast");
    this.cardImageStore = new Map();
    this.cardIdCounter = 0;
    this.imageIdCounter = 0;
    this.warningTimer = null;
    this.toastTimer = null;
  }

  init() {
    this.bindEvents();
    this.addProductCard({}, { focus: false, notify: false });
    this.updateFeaturedState();
  }

  buildFormData() {
  const formData = new FormData();
  const cards = this.getProductCards();

  cards.forEach((card, index) => {
    const prefix = `products[${index}]`;

    // Get each field safely with null checks
    const category = card.querySelector("[data-field='category']");
    const name = card.querySelector("[data-field='name']");
    const description = card.querySelector("[data-field='description']");
    const price = card.querySelector("[data-field='price']");
    const stock = card.querySelector("[data-field='stock']");
    const isFeatured = card.querySelector("[data-field='is_featured']"); // Fixed: was 'featured'

    // Add form fields with null checks
    formData.append(`${prefix}[category]`, category ? category.value : '');
    formData.append(`${prefix}[name]`, name ? name.value : '');
    formData.append(`${prefix}[description]`, description ? description.value : '');
    formData.append(`${prefix}[price]`, price ? price.value : '');
    formData.append(`${prefix}[stock]`, stock ? stock.value : '');
    formData.append(`${prefix}[is_featured]`, isFeatured ? isFeatured.checked : false);

    // Add images
    const cardKey = this.getCardKey(card);
    const images = this.cardImageStore.get(cardKey) || [];

    images.forEach((img) => {
      formData.append(`${prefix}[images][]`, img.file);
    });
  });

  return formData;
}

getCSRFToken() {
  // First try to get from hidden input if it exists
  const csrfInput = document.querySelector('input[name="csrfmiddlewaretoken"]');
  if (csrfInput) {
    return csrfInput.value;
  }
  
  // Fallback to cookie method
  const name = 'csrftoken=';
  const decodedCookie = decodeURIComponent(document.cookie);
  const ca = decodedCookie.split(';');
  for (let i = 0; i < ca.length; i++) {
    let c = ca[i].trim();
    if (c.indexOf(name) === 0) {
      return c.substring(name.length, c.length);
    }
  }
  return '';
}

  bindEvents() {
    this.addButton.addEventListener("click", () => {
      this.addProductCard(this.getSeedFromLastCard());
    });

    this.cancelButton.addEventListener("click", () => {
      this.resetToSingleCard();
      this.showToast("Draft cleared. Ready for a new batch.");
    });


    this.form.addEventListener("submit", async (event) => {
        event.preventDefault();

  if (!this.form.reportValidity()) return;

  const formData = this.buildFormData();
  
  // Add CSRF token to FormData (in case the cookie method fails)
  const csrfToken = this.getCSRFToken();
  if (csrfToken) {
    formData.append('csrfmiddlewaretoken', csrfToken);
  }

  try {
    const response = await fetch("/products/create_product_api/", {
      method: "POST",
      body: formData,
      headers: {
        "X-CSRFToken": csrfToken,
        // Don't set Content-Type header - browser will set it with boundary for FormData
      },
      // Add credentials to ensure cookies are sent
      credentials: 'same-origin'
    });

    const result = await response.json();

    if (response.ok) {
      this.showToast("Products saved successfully!");
      this.resetToSingleCard();
    } else {
      this.showWarning(result.error || "Failed to save products.");
    }
  } catch (err) {
    console.error('Submission error:', err);
    this.showWarning("Network error. Try again.");
  }

  console.log('CSRF Token:', this.getCSRFToken());
    console.log('FormData entries:');
    for (let pair of formData.entries()) {
        console.log(pair[0], pair[1]);
    }
});

    this.productList.addEventListener("click", (event) => {
      this.handleProductListClick(event);
    });

    this.productList.addEventListener("change", async (event) => {
      await this.handleProductListChange(event);
    });

    this.productList.addEventListener("dragenter", (event) => {
      const dropzone = this.getDropzoneFromEvent(event);

      if (!dropzone) {
        return;
      }

      event.preventDefault();
      this.toggleDropzoneState(dropzone, true);
    });

    this.productList.addEventListener("dragover", (event) => {
      const dropzone = this.getDropzoneFromEvent(event);

      if (!dropzone) {
        return;
      }

      event.preventDefault();
      if (event.dataTransfer) {
        event.dataTransfer.dropEffect = "copy";
      }
      this.toggleDropzoneState(dropzone, true);
    });

    this.productList.addEventListener("dragleave", (event) => {
      const dropzone = this.getDropzoneFromEvent(event);

      if (!dropzone) {
        return;
      }

      const nextTarget = event.relatedTarget;
      if (nextTarget && dropzone.contains(nextTarget)) {
        return;
      }

      this.toggleDropzoneState(dropzone, false);
    });

    this.productList.addEventListener("drop", async (event) => {
      const dropzone = this.getDropzoneFromEvent(event);

      if (!dropzone) {
        return;
      }

      event.preventDefault();
      this.toggleDropzoneState(dropzone, false);

      const files = Array.from(event.dataTransfer?.files || []);
      const card = dropzone.closest("[data-product-card]");
      await this.addImagesToCard(card, files);
    });
  }

  handleProductListClick(event) {
    const removeProductButton = event.target.closest("[data-remove-product]");

    if (removeProductButton) {
      const card = removeProductButton.closest("[data-product-card]");
      this.removeProductCard(card);
      return;
    }

    const removeImageButton = event.target.closest("[data-remove-image]");

    if (removeImageButton) {
      const card = removeImageButton.closest("[data-product-card]");
      this.removeImageFromCard(card, removeImageButton.dataset.removeImage);
      return;
    }

    const uploadButton = event.target.closest("[data-upload-button]");

    if (uploadButton) {
      const imageInput = uploadButton
        .closest("[data-image-upload]")
        .querySelector("[data-field='images']");

      imageInput.value = "";
      imageInput.click();
      return;
    }

    const toggleControl = event.target.closest("[data-toggle-control]");

    if (!toggleControl) {
      return;
    }

    const toggleInput = toggleControl.querySelector("[data-field='is_featured']");

    if (toggleInput && toggleInput.disabled && !toggleInput.checked) {
      event.preventDefault();
      this.showWarning("Only 3 products can be featured at a time.");
    }
  }

  async handleProductListChange(event) {
    const target = event.target;

    if (target.matches("[data-field='is_featured']")) {
      this.updateFeaturedState();
      return;
    }

    if (target.matches("[data-field='images']")) {
      const card = target.closest("[data-product-card]");
      const files = Array.from(target.files || []);
      await this.addImagesToCard(card, files);
    }
  }

  getDropzoneFromEvent(event) {
    return event.target.closest("[data-upload-button]");
  }

  toggleDropzoneState(dropzone, isActive) {
    dropzone.classList.toggle("image-upload__dropzone--active", isActive);
  }

  getProductCards() {
    return Array.from(this.productList.querySelectorAll("[data-product-card]"));
  }

  getCardKey(card) {
    return card?.dataset.cardKey || "";
  }

  getSeedFromLastCard() {
    const lastCard = this.getProductCards().at(-1);

    if (!lastCard) {
      return {};
    }

    return {
      category: lastCard.querySelector("[data-field='category']").value
    };
  }

  addProductCard(seed = {}, options = {}) {
    const settings = {
      focus: true,
      notify: true,
      ...options
    };

    const fragment = this.template.content.cloneNode(true);
    const card = fragment.querySelector("[data-product-card]");
    const cardKey = `product-card-${++this.cardIdCounter}`;

    card.dataset.cardKey = cardKey;
    this.cardImageStore.set(cardKey, []);

    if (seed.category) {
      card.querySelector("[data-field='category']").value = seed.category;
    }

    this.productList.appendChild(fragment);
    this.refreshCards();
    this.renderImagePreview(card);

    const focusTarget = seed.category
      ? card.querySelector("[data-field='name']")
      : card.querySelector("[data-field='category']");

    if (settings.focus) {
      focusTarget.focus();
    }

    if (settings.notify) {
      this.showToast("New product card added.");
    }
  }

  removeProductCard(card) {
    const cards = this.getProductCards();

    if (!card || cards.length === 1) {
      this.showWarning("At least one product card must remain on the page.");
      return;
    }

    this.cardImageStore.delete(this.getCardKey(card));
    card.remove();
    this.refreshCards();
    this.showToast("Product card removed.");
  }

  resetToSingleCard() {
    this.cardImageStore.clear();
    this.productList.innerHTML = "";
    this.hideWarning();
    this.addProductCard({}, { notify: false });
    this.updateFeaturedState();
  }

  refreshCards() {
    this.getProductCards().forEach((card, index, cards) => {
      this.syncCardIdentifiers(card, index);

      const removeButton = card.querySelector("[data-remove-product]");
      removeButton.disabled = cards.length === 1;
    });

    this.updateFeaturedState();
  }

  syncCardIdentifiers(card, index) {
    const productNumber = index + 1;
    card.querySelector("[data-product-title]").textContent = `Product #${productNumber}`;

    const fields = card.querySelectorAll("[data-field]");
    fields.forEach((field) => {
      const fieldName = field.dataset.field;
      const fieldId = `product-${productNumber}-${fieldName}`;

      field.id = fieldId;
      field.name = fieldName === "images"
        ? `products[${index}][images][]`
        : `products[${index}][${fieldName}]`;

      const label = card.querySelector(`[data-label-for='${fieldName}']`);
      if (label) {
        label.htmlFor = fieldId;
      }
    });
  }

  updateFeaturedState() {
    const toggleInputs = this.getProductCards().map((card) =>
      card.querySelector("[data-field='is_featured']")
    );

    const featuredCount = toggleInputs.filter((toggle) => toggle.checked).length;
    this.counter.textContent = `Featured: ${featuredCount} / ${this.featuredLimit}`;
    this.counter.classList.toggle(
      "counter-badge--limit",
      featuredCount >= this.featuredLimit
    );

    toggleInputs.forEach((toggle) => {
      const shouldDisable = featuredCount >= this.featuredLimit && !toggle.checked;
      const toggleControl = toggle.closest("[data-toggle-control]");
      const toggleStatus = toggleControl.querySelector("[data-toggle-status]");

      toggle.disabled = shouldDisable;
      toggleControl.classList.toggle("toggle-switch--disabled", shouldDisable);

      if (toggle.checked) {
        toggleStatus.textContent = "Featured on storefront";
      } else if (shouldDisable) {
        toggleStatus.textContent = "Limit reached";
      } else {
        toggleStatus.textContent = "Not featured";
      }
    });
  }

  async addImagesToCard(card, files) {
    if (!card || !files.length) {
      return;
    }

    const imageFiles = files.filter((file) => this.isImageFile(file));
    const skippedCount = files.length - imageFiles.length;

    if (!imageFiles.length) {
      this.showWarning("Only image files can be uploaded.");
      return;
    }

    try {
      const imageEntries = await Promise.all(
        imageFiles.map(async (file) => ({
          id: `image-${++this.imageIdCounter}`,
          file,
          src: await this.readFileAsDataUrl(file)
        }))
      );

      const cardKey = this.getCardKey(card);
      const existingImages = this.cardImageStore.get(cardKey) || [];
      this.cardImageStore.set(cardKey, existingImages.concat(imageEntries));
      this.syncImageInput(card);
      this.renderImagePreview(card);

      if (skippedCount > 0) {
        this.showWarning("Some files were skipped because they are not images.");
      }

      this.showToast(
        `${imageFiles.length} image${imageFiles.length === 1 ? "" : "s"} added.`
      );
    } catch (error) {
      this.showWarning("One or more images could not be previewed.");
    }
  }

  isImageFile(file) {
    return Boolean(file && typeof file.type === "string" && file.type.startsWith("image/"));
  }

  readFileAsDataUrl(file) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();

      reader.onload = () => resolve(String(reader.result));
      reader.onerror = () => reject(new Error("Unable to read file."));
      reader.readAsDataURL(file);
    });
  }

  syncImageInput(card) {
    const imageInput = card.querySelector("[data-field='images']");
    const images = this.cardImageStore.get(this.getCardKey(card)) || [];

    if (!imageInput || typeof DataTransfer !== "function") {
      return;
    }

    const dataTransfer = new DataTransfer();
    images.forEach((image) => dataTransfer.items.add(image.file));

    try {
      imageInput.files = dataTransfer.files;
    } catch (error) {
      return;
    }
  }

  renderImagePreview(card) {
    const previewContainer = card.querySelector("[data-image-preview]");
    const imageCountLabel = card.querySelector("[data-image-count]");
    const images = this.cardImageStore.get(this.getCardKey(card)) || [];

    previewContainer.innerHTML = "";
    imageCountLabel.textContent = images.length
      ? `${images.length} image${images.length === 1 ? "" : "s"} ready to upload`
      : "No images uploaded yet";

    if (!images.length) {
      const emptyState = document.createElement("div");
      emptyState.className = "image-preview__empty";
      emptyState.textContent = "Selected images will appear here.";
      previewContainer.appendChild(emptyState);
      return;
    }

    images.forEach((image) => {
      const previewItem = document.createElement("article");
      previewItem.className = "image-preview__item";
      previewItem.innerHTML = `
        <button
          class="image-preview__remove"
          data-remove-image="${image.id}"
          type="button"
          aria-label="Remove ${this.escapeHtml(image.file.name)}"
        >
          X
        </button>
        <div class="image-preview__thumb">
          <img class="image-preview__image" src="${image.src}" alt="${this.escapeHtml(image.file.name)} preview">
        </div>
        <div class="image-preview__details">
          <p class="image-preview__name">${this.escapeHtml(image.file.name)}</p>
          <p class="image-preview__size">${this.formatFileSize(image.file.size)}</p>
        </div>
      `;
      previewContainer.appendChild(previewItem);
    });
  }

  removeImageFromCard(card, imageId) {
    const cardKey = this.getCardKey(card);
    const currentImages = this.cardImageStore.get(cardKey) || [];
    const updatedImages = currentImages.filter((image) => image.id !== imageId);

    if (updatedImages.length === currentImages.length) {
      return;
    }

    this.cardImageStore.set(cardKey, updatedImages);
    this.syncImageInput(card);
    this.renderImagePreview(card);
    this.showToast("Image removed.");
  }

  getTotalImageCount() {
    return Array.from(this.cardImageStore.values()).reduce(
      (total, images) => total + images.length,
      0
    );
  }

  formatFileSize(bytes) {
    if (bytes < 1024) {
      return `${bytes} B`;
    }

    if (bytes < 1024 * 1024) {
      return `${(bytes / 1024).toFixed(1)} KB`;
    }

    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }

  escapeHtml(value) {
    const stringValue = String(value);
    const escapeMap = {
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      "\"": "&quot;",
      "'": "&#39;"
    };

    return stringValue.replace(/[&<>"']/g, (character) => escapeMap[character]);
  }

  showWarning(message) {
    this.warningBanner.textContent = message;
    this.warningBanner.hidden = false;
    window.clearTimeout(this.warningTimer);
    this.warningTimer = window.setTimeout(() => this.hideWarning(), 2800);
  }

  hideWarning() {
    this.warningBanner.hidden = true;
    this.warningBanner.textContent = "";
  }

  showToast(message) {
    this.toast.textContent = message;
    this.toast.classList.add("is-visible");
    window.clearTimeout(this.toastTimer);
    this.toastTimer = window.setTimeout(() => {
      this.toast.classList.remove("is-visible");
    }, 2200);
  }
}

window.addEventListener("DOMContentLoaded", () => {
  const productCreationUI = new ProductCreationUI();
  productCreationUI.init();
});
