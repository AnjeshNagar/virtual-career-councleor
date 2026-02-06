// Mobile Navigation Menu JavaScript - Simplified
document.addEventListener('DOMContentLoaded', function() {
    const mobileMenuToggle = document.getElementById('mobileMenuToggle');
    const mainNav = document.getElementById('mainNav');
    
    // Only handle mobile menu toggle, let CSS handle desktop dropdowns
    if (mobileMenuToggle && mainNav) {
        mobileMenuToggle.addEventListener('click', function() {
            mainNav.classList.toggle('active');
            
            // Animate hamburger menu
            const spans = mobileMenuToggle.querySelectorAll('span');
            if (mainNav.classList.contains('active')) {
                spans[0].style.transform = 'rotate(45deg) translate(5px, 5px)';
                spans[1].style.opacity = '0';
                spans[2].style.transform = 'rotate(-45deg) translate(7px, -6px)';
            } else {
                spans[0].style.transform = 'none';
                spans[1].style.opacity = '1';
                spans[2].style.transform = 'none';
            }
        });
        
        // Close menu when clicking outside
        document.addEventListener('click', function(event) {
            if (!mainNav.contains(event.target) && !mobileMenuToggle.contains(event.target)) {
                mainNav.classList.remove('active');
                const spans = mobileMenuToggle.querySelectorAll('span');
                spans[0].style.transform = 'none';
                spans[1].style.opacity = '1';
                spans[2].style.transform = 'none';
            }
        });
    }
    
    // Mobile dropdown handling - only add click listeners on mobile
    function setupMobileDropdowns() {
        const dropdownToggles = document.querySelectorAll('.dropdown-toggle');
        
        if (window.innerWidth <= 768) {
            dropdownToggles.forEach(toggle => {
                // Remove any existing click listeners
                const newToggle = toggle.cloneNode(true);
                toggle.parentNode.replaceChild(newToggle, toggle);
                
                newToggle.addEventListener('click', function(e) {
                    e.preventDefault();
                    e.stopPropagation();
                    const dropdown = this.closest('.nav-dropdown');
                    dropdown.classList.toggle('active');
                    
                    // Close other dropdowns
                    document.querySelectorAll('.nav-dropdown').forEach(otherDropdown => {
                        if (otherDropdown !== dropdown) {
                            otherDropdown.classList.remove('active');
                        }
                    });
                });
            });
        } else {
            // On desktop, remove active classes
            document.querySelectorAll('.nav-dropdown').forEach(dropdown => {
                dropdown.classList.remove('active');
            });
        }
    }
    
    // Initial setup
    setupMobileDropdowns();
    
    // Handle window resize
    let resizeTimer;
    window.addEventListener('resize', function() {
        clearTimeout(resizeTimer);
        resizeTimer = setTimeout(function() {
            if (window.innerWidth > 768) {
                mainNav.classList.remove('active');
                document.querySelectorAll('.nav-dropdown').forEach(dropdown => {
                    dropdown.classList.remove('active');
                });
            }
            setupMobileDropdowns();
        }, 250);
    });
});
