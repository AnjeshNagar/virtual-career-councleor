// Dark Mode Toggle
(function() {
    // Check for saved theme preference or default to light mode
    const currentTheme = localStorage.getItem('theme') || 'light';
    
    if (currentTheme === 'dark') {
        document.body.classList.add('dark-mode');
    }
    
    // Create toggle button
    const toggleBtn = document.createElement('button');
    toggleBtn.className = 'dark-mode-toggle';
    toggleBtn.innerHTML = currentTheme === 'dark' ? '☀️' : '🌙';
    toggleBtn.title = 'Toggle Dark Mode';
    toggleBtn.setAttribute('aria-label', 'Toggle Dark Mode');
    document.body.appendChild(toggleBtn);
    
    // Toggle function
    toggleBtn.addEventListener('click', () => {
        document.body.classList.toggle('dark-mode');
        const isDark = document.body.classList.contains('dark-mode');
        toggleBtn.innerHTML = isDark ? '☀️' : '🌙';
        localStorage.setItem('theme', isDark ? 'dark' : 'light');
    });
})();
