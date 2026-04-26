// SEARCH FUNCTIONALITY 
(function() {
    const searchForm = document.getElementById('searchForm');
    const searchInput = document.getElementById('searchInput');
    const searchIcon = document.getElementById('searchIcon');
    const searchSpinner = document.getElementById('searchSpinner');
    const clearSearchBtn = document.getElementById('clearSearchBtn');
    const productsTableBody = document.getElementById('productsTableBody');
    const itemCount = document.getElementById('itemCount');
    const paginationFooter = document.getElementById('paginationFooter');
    const paginationSummary = document.getElementById('paginationSummary');
    const paginationControls = document.getElementById('paginationControls');
    
    let searchTimeout;
    let currentQuery = '';
    let currentPage = 1;
    
    function getCSRFToken() {
        const cookie = document.cookie.split('; ').find(row => row.startsWith('csrftoken='));
        return cookie ? cookie.split('=')[1] : '';
    }
    
    function setLoading(loading) {
        searchIcon.style.display = loading ? 'none' : 'block';
        searchSpinner.style.display = loading ? 'block' : 'none';
        if (loading) {
            productsTableBody.style.opacity = '0.5';
        } else {
            productsTableBody.style.opacity = '1';
        }
    }
    
    function toggleClearButton() {
        clearSearchBtn.style.display = searchInput.value.length > 0 ? 'inline-block' : 'none';
    }

    function formatTsh(price) {
      const amount = Math.round(parseFloat(price));
      return 'Tsh ' + amount.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ',');
    }

    function escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
    
    function renderProductRow(product) {
        const imageHtml = product.image_url 
            ? `<img class="media-object__thumb" src="${product.image_url}" alt="${escapeHtml(product.name)}" style="width: 48px; height: 48px; object-fit: cover; border-radius: 12px;">`
            : `<span class="media-object__thumb media-object__thumb--slate" aria-hidden="true"><i class="fa-solid fa-image"></i></span>`;
        
        return `
            <tr class="data-table__row">
                <td class="data-table__cell">${imageHtml}</td>
                <td class="data-table__cell"><div class="table-item"><strong class="table-item__title">${escapeHtml(product.name)}</strong></div></td>
                <td class="data-table__cell">Tsh ${formatTsh(product.price)}</td>
                <td class="data-table__cell">${product.stock}</td>
                <td class="data-table__cell">
                    ${product.is_available 
                        ? '<span class="badge badge--success available-badge">Active</span>'
                        : '<span class="badge badge--danger available-badge">Inactive</span>'}
                </td>
                <td class="data-table__cell">
                    ${product.is_featured 
                        ? '<span class="badge badge--warning featured-badge">Featured</span>'
                        : '<span class="badge badge--neutral featured-badge">Not featured</span>'}
                </td>
                <td class="data-table__cell data-table__cell--actions">
                    <div class="table-actions">
                        <a class="btn btn--secondary btn--sm" href="/products/product/${product.id}/edit/">
                            <i class="fa-solid fa-pen-to-square"></i><span>Edit</span>
                        </a>
                        <button class="btn btn--danger btn--soft btn--sm delete-product-btn" data-product-id="${product.id}" data-product-name="${escapeHtml(product.name)}" type="button">
                            <i class="fa-solid fa-trash"></i><span>Delete</span>
                        </button>
                        <button class="btn btn--success btn--sm toggle-featured-btn" data-product-id="${product.id}" type="button">
                            <i class="fa-solid fa-star"></i><span>${product.is_featured ? 'Unfeature' : 'Feature'}</span>
                        </button>
                    </div>
                </td>
            </tr>`;
    }
    
    function renderPagination(currentPageNum, totalPages, totalCount) {
        if (totalPages <= 1) {
            paginationFooter.style.display = 'none';
            return;
        }
        paginationFooter.style.display = '';
        
        const start = (currentPageNum - 1) * 10 + 1;
        const end = Math.min(currentPageNum * 10, totalCount);
        paginationSummary.textContent = `Showing ${start}-${end} of ${totalCount} products`;
        
        let html = '';
        
        // Previous
        if (currentPageNum > 1) {
            html += `<button class="pagination__button search-page-btn" data-page="${currentPageNum - 1}"><i class="fa-solid fa-chevron-left"></i><span>Previous</span></button>`;
        } else {
            html += `<button class="pagination__button" type="button" disabled><i class="fa-solid fa-chevron-left"></i><span>Previous</span></button>`;
        }
        
        // Page numbers
        const maxVisible = 5;
        let startPage = Math.max(1, currentPageNum - Math.floor(maxVisible / 2));
        let endPage = Math.min(totalPages, startPage + maxVisible - 1);
        if (endPage - startPage + 1 < maxVisible) startPage = Math.max(1, endPage - maxVisible + 1);
        
        for (let i = startPage; i <= endPage; i++) {
            const active = i === currentPageNum ? ' pagination__button--active' : '';
            html += `<button class="pagination__button search-page-btn${active}" data-page="${i}">${i}</button>`;
        }
        
        // Next
        if (currentPageNum < totalPages) {
            html += `<button class="pagination__button search-page-btn" data-page="${currentPageNum + 1}"><span>Next</span><i class="fa-solid fa-chevron-right"></i></button>`;
        } else {
            html += `<button class="pagination__button" type="button" disabled><span>Next</span><i class="fa-solid fa-chevron-right"></i></button>`;
        }
        
        paginationControls.innerHTML = html;
        
        // Bind page buttons
        paginationControls.querySelectorAll('.search-page-btn').forEach(btn => {
            btn.addEventListener('click', function() {
                searchProducts(currentQuery, parseInt(this.dataset.page));
            });
        });
    }
    
    async function searchProducts(query, page = 1) {
        currentQuery = query;
        currentPage = page;
        setLoading(true);
        
        try {
            const response = await fetch(`/products/search_products_api/?query=${encodeURIComponent(query)}&page=${page}`);
            const data = await response.json();
            
            if (data.products.length === 0) {
                productsTableBody.innerHTML = `<tr class="data-table__row"><td class="data-table__cell" colspan="7">${query ? 'No products match your search.' : 'No products found.'}</td></tr>`;
            } else {
                productsTableBody.innerHTML = data.products.map(renderProductRow).join('');
            }
            
            itemCount.textContent = `${data.total_count} items`;
            renderPagination(data.current_page, data.total_pages, data.total_count);
            
            if (page > 1 || query) {
                document.getElementById('inventory-heading').scrollIntoView({ behavior: 'smooth' });
            }
            
            // Re-trigger external JS events
            document.dispatchEvent(new CustomEvent('productsTableUpdated'));
        } catch (error) {
            console.error('Search error:', error);
        } finally {
            setLoading(false);
        }
    }
    
    function clearSearch() {
        searchInput.value = '';
        toggleClearButton();
        searchProducts('', 1);
        searchInput.focus();
    }
    
    // Event listeners
    searchInput.addEventListener('input', function() {
        toggleClearButton();
        clearTimeout(searchTimeout);
        searchTimeout = setTimeout(() => searchProducts(this.value.trim(), 1), 300);
    });
    
    searchForm.addEventListener('submit', function(e) {
        e.preventDefault();
        clearTimeout(searchTimeout);
        searchProducts(searchInput.value.trim(), 1);
    });
    
    clearSearchBtn.addEventListener('click', clearSearch);
    
    // Initial state
    toggleClearButton();
})();

