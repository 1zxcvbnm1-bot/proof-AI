document.addEventListener('DOMContentLoaded', () => {
  // Navigation Routing Logic
  const navLinks = document.querySelectorAll('.nav-link[data-target]');
  const viewSections = document.querySelectorAll('.view-section');
  const headerTitle = document.getElementById('current-view-title');

  function navigateTo(targetId) {
    // Hide all sections
    viewSections.forEach(section => {
      section.classList.remove('active');
    });

    // Deselect all links
    navLinks.forEach(link => {
      link.classList.remove('active');
    });

    // Show target section
    const targetSection = document.getElementById(`view-${targetId}`);
    if (targetSection) {
      targetSection.classList.add('active');
    }

    // Highlight active link
    const targetLink = document.querySelector(`.nav-link[data-target="${targetId}"]`);
    if (targetLink) {
      targetLink.classList.add('active');
      
      // Update header title based on navigation item
      const linkText = targetLink.querySelector('span:not(.nav-icon)').innerText;
      if (headerTitle) {
        headerTitle.innerText = linkText;
      }
    }
  }

  // Setup click listeners for nav
  navLinks.forEach(link => {
    link.addEventListener('click', (e) => {
      e.preventDefault();
      const targetId = link.getAttribute('data-target');
      navigateTo(targetId);
      
      // Update URL hash without scroll jumping
      history.replaceState(null, null, `#${targetId}`);
    });
  });

  // Handle initial load based on hash
  const initialHash = window.location.hash.substring(1);
  if (initialHash && document.getElementById(`view-${initialHash}`)) {
    navigateTo(initialHash);
  } else {
    navigateTo('dashboard'); // Default view
  }

  // Demo: Interactive Terminal Output Generation
  const terminalDisplays = document.querySelectorAll('.terminal-body');
  
  function addTerminalLine(terminalBody, text, type = 'info') {
    const line = document.createElement('div');
    line.className = 'terminal-line';
    
    let colorPrefix = '';
    if (type === 'error') line.style.color = 'var(--danger)';
    if (type === 'warning') line.style.color = 'var(--warning)';
    
    line.innerHTML = `<span class="terminal-prompt">&gt;</span> ${text}`;
    terminalBody.appendChild(line);
    terminalBody.scrollTop = terminalBody.scrollHeight;
  }

  // Simple mock API call logic
  document.querySelectorAll('.mock-api-btn').forEach(btn => {
    btn.addEventListener('click', (e) => {
      const targetTerminal = e.target.closest('.service-interface').querySelector('.terminal-body');
      const action = e.target.getAttribute('data-action');
      const service = e.target.getAttribute('data-service');
      
      addTerminalLine(targetTerminal, `Initializing request to /v1/${service}/${action}...`, 'info');
      
      setTimeout(() => {
        addTerminalLine(targetTerminal, `Status: 200 OK`, 'info');
        addTerminalLine(targetTerminal, `Response Object Generated.`, 'info');
        
        let mockResponse = '';
        if (service === 'rag') {
            mockResponse = '{\n  "context_retrieved": 5,\n  "sources": ["doc_1", "doc_3"],\n  "confidence": 0.94\n}';
        } else if (service === 'fact-checker') {
            mockResponse = '{\n  "status": "verified",\n  "truth_score": 0.98,\n  "hallucination_detected": false\n}';
        } else if (service === 'agent-loop') {
            mockResponse = '{\n  "status": "running",\n  "current_phase": "execution",\n  "tools_used": ["search"]\n}';
        } else {
            mockResponse = '{\n  "status": "success"\n}';
        }
        
        addTerminalLine(targetTerminal, `<pre style="font-family:inherit;margin-top:5px;opacity:0.8">${mockResponse}</pre>`, 'info');
      }, 800);
    });
  });

  // Copy API Key Functionality
  document.querySelectorAll('.copy-btn').forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.preventDefault();
      const keyText = e.target.closest('td').querySelector('.api-key-cell').innerText;
      
      navigator.clipboard.writeText(keyText).then(() => {
        const originalText = btn.innerText;
        btn.innerText = 'Copied!';
        setTimeout(() => {
          btn.innerText = originalText;
        }, 2000);
      });
    });
  });
});
