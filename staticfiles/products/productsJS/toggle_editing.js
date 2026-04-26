document.addEventListener('DOMContentLoaded', function() {
    console.log('Dashboard JS loaded');
    
    // Get CSRF token
    function getCSRFToken() {
        const csrfInput = document.querySelector('input[name="csrfmiddlewaretoken"]');
        if (csrfInput) return csrfInput.value;
        
        const cookie = document.cookie
            .split('; ')
            .find(row => row.startsWith('csrftoken='));
        return cookie ? cookie.split('=')[1] : '';
    }

    // Toast notification function
    function showToast(message, type = 'success') {
        const toast = document.createElement('div');
        toast.style.cssText = `
            position: fixed;
            right: 24px;
            bottom: 24px;
            min-width: 240px;
            max-width: min(360px, calc(100% - 2rem));
            padding: 14px 18px;
            border-radius: 18px;
            background: ${type === 'success' ? 'rgba(11, 139, 116, 0.95)' : 'rgba(204, 69, 99, 0.95)'};
            color: #ffffff;
            box-shadow: 0 22px 40px rgba(15, 24, 43, 0.24);
            z-index: 9999;
            font-weight: 600;
            transition: opacity 0.3s ease, transform 0.3s ease;
            transform: translateY(20px);
            opacity: 0;
        `;
        toast.textContent = message;
        document.body.appendChild(toast);
        
        setTimeout(() => {
            toast.style.opacity = '1';
            toast.style.transform = 'translateY(0)';
        }, 100);
        
        setTimeout(() => {
            toast.style.opacity = '0';
            toast.style.transform = 'translateY(20px)';
            setTimeout(() => toast.remove(), 300);
        }, 3000);
    }

    function updateFeaturedMeter() {
        const featuredSlots = document.querySelectorAll('.slot-card:not(.slot-card--placeholder)').length;
        const progressBar = document.querySelector('.progress');
        const usageText = document.querySelector('.slot-module__usage');
        const featuredMeter = document.querySelector('.metric-card:nth-child(4) .metric-card__value');
        
        if (progressBar) {
            progressBar.value = featuredSlots;
        }
        
        if (usageText) {
            const maxFeatured = parseInt(progressBar?.max) || 3;
            usageText.textContent = `Featured usage: ${featuredSlots}/${maxFeatured}`;
        }
        
        if (featuredMeter) {
            featuredMeter.textContent = featuredSlots;
        }
    }

    function updateToggleButtons(featuredCount) {
        const progressBar = document.querySelector('.progress');
        const maxFeatured = parseInt(progressBar?.max) || 3;
        const toggleButtons = document.querySelectorAll('.toggle-featured-btn');
        
        toggleButtons.forEach(btn => {
            const row = btn.closest('tr');
            const featuredBadge = row?.querySelector('.featured-badge');
            const isCurrentlyFeatured = featuredBadge && featuredBadge.textContent.trim() === 'Featured';
            
            if (!isCurrentlyFeatured && featuredCount >= maxFeatured) {
                btn.disabled = true;
                btn.title = 'Maximum featured products reached';
            } else {
                btn.disabled = false;
                btn.title = '';
            }
        });
    }

    // ========================================
    // TOGGLE FEATURED IN TABLE
    // ========================================
    document.querySelectorAll('.toggle-featured-btn').forEach(btn => {
        console.log('Toggle button found:', btn.dataset.productId);
        
        btn.addEventListener('click', async function() {
            const productId = this.dataset.productId;
            const row = this.closest('tr');
            
            if (!productId || productId === 'None') {
                showToast('Cannot toggle demo products', 'error');
                return;
            }
            
            this.disabled = true;
            
            try {
                const response = await fetch(`/products/product/${productId}/toggle_featured/`, {
                    method: 'POST',
                    headers: {
                        'X-CSRFToken': getCSRFToken(),
                    }
                });
                
                const data = await response.json();
                console.log('Toggle response:', data);
                
                if (response.ok) {
                    const featuredBadge = row.querySelector('.featured-badge');
                    if (data.is_featured) {
                        featuredBadge.className = 'badge badge--warning featured-badge';
                        featuredBadge.textContent = 'Featured';
                        this.querySelector('span').textContent = 'Unfeature';
                    } else {
                        featuredBadge.className = 'badge badge--neutral featured-badge';
                        featuredBadge.textContent = 'Not featured';
                        this.querySelector('span').textContent = 'Feature';
                    }
                    
                    showToast(data.message || 'Featured status updated!', 'success');
                    setTimeout(() => location.reload(), 1500);
                } else {
                    showToast(data.error || 'Failed to toggle featured status', 'error');
                }
            } catch (error) {
                console.error('Error:', error);
                showToast('Network error occurred', 'error');
            } finally {
                this.disabled = false;
            }
        });
    });

    // ========================================
    // DELETE PRODUCT
    // ========================================
    document.querySelectorAll('.delete-product-btn').forEach(btn => {
        console.log('Delete button found:', btn.dataset.productId);
        
        btn.addEventListener('click', async function() {
            const productId = this.dataset.productId;
            const productName = this.dataset.productName;
            
            if (!productId || productId === 'None') {
                showToast('Cannot delete demo products', 'error');
                return;
            }
            
            if (!confirm(`Are you sure you want to delete "${productName}"? This action cannot be undone.`)) {
                return;
            }
            
            const row = this.closest('tr');
            this.disabled = true;
            
            try {
                const response = await fetch(`/products/product/${productId}/delete_api/`, {
                    method: 'POST',
                    headers: {
                        'X-CSRFToken': getCSRFToken(),
                    }
                });
                
                const data = await response.json();
                console.log('Delete response:', data);
                
                if (response.ok) {
                    showToast(data.message || 'Product deleted!', 'success');
                    row.style.opacity = '0';
                    row.style.transition = 'opacity 0.3s';
                    setTimeout(() => {
                        row.remove();
                        const remainingRows = document.querySelectorAll('.data-table__body .data-table__row').length;
                        if (remainingRows <= 1) {
                            location.reload();
                        }
                    }, 300);
                } else {
                    showToast(data.error || 'Failed to delete product', 'error');
                }
            } catch (error) {
                console.error('Error:', error);
                showToast('Network error occurred', 'error');
            } finally {
                this.disabled = false;
            }
        });
    });

    // ========================================
    // REMOVE FEATURED FROM SLOTS
    // ========================================
    document.querySelectorAll('.remove-featured-btn').forEach(btn => {
        console.log('Remove featured button found:', btn.dataset.productId);
        
        btn.addEventListener('click', async function() {
            const productId = this.dataset.productId;
            const productName = this.dataset.productName;
            const slotCard = this.closest('.slot-card');
            
            console.log('Remove button clicked:', productId, productName);
            
            if (!productId || productId === 'None') {
                showToast('Cannot remove demo products', 'error');
                return;
            }
            
            if (!confirm(`Remove "${productName}" from featured products?`)) {
                return;
            }
            
            this.disabled = true;
            
            try {
                const response = await fetch(`/products/product/${productId}/toggle_featured/`, {
                    method: 'POST',
                    headers: {
                        'X-CSRFToken': getCSRFToken(),
                    }
                });
                
                const data = await response.json();
                console.log('Remove featured response:', data);
                
                if (response.ok) {
                    showToast(`${productName} removed from featured products`, 'success');
                    
                    // Replace with placeholder
                    slotCard.style.opacity = '0';
                    slotCard.style.transition = 'opacity 0.3s ease';
                    
                    setTimeout(() => {
                        slotCard.className = 'slot-card slot-card--placeholder';
                        slotCard.innerHTML = `
                            <span class="slot-card__placeholder-icon" aria-hidden="true">
                                <i class="fa-solid fa-plus"></i>
                            </span>
                            <div class="slot-card__placeholder-copy">
                                <h3 class="slot-card__title">Add to Featured</h3>
                                <p class="slot-card__description">This slot is empty.</p>
                            </div>
                            <button class="btn btn--secondary btn--sm btn--full" type="button" disabled>
                                <i class="fa-solid fa-star" aria-hidden="true"></i>
                                <span>Choose Product</span>
                            </button>
                        `;
                        
                        slotCard.style.opacity = '1';
                        updateFeaturedMeter();
                    }, 300);
                    
                    setTimeout(() => location.reload(), 2000);
                } else {
                    showToast(data.error || 'Failed to remove featured status', 'error');
                }
            } catch (error) {
                console.error('Error:', error);
                showToast('Network error occurred', 'error');
            } finally {
                this.disabled = false;
            }
        });
    });
});