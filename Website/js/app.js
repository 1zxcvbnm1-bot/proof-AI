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

  // Real API call for Fact Checker
  const factCheckBtn = document.querySelector('.mock-api-btn[data-service="fact-checker"]');
  if (factCheckBtn) {
    factCheckBtn.addEventListener('click', async (e) => {
      const targetTerminal = e.target.closest('.service-interface').querySelector('.terminal-body');
      const terminalBody = document.getElementById('factcheck-terminal') || targetTerminal;

      // Clear terminal
      terminalBody.innerHTML = '';

      // Get user inputs
      const provider = document.getElementById('factcheck-provider')?.value || 'groq';
      const apiKey = document.getElementById('factcheck-apikey')?.value?.trim();
      const model = document.getElementById('factcheck-model')?.value?.trim() || undefined;
      const query = document.getElementById('factcheck-query')?.value?.trim();

      if (!apiKey) {
        addTerminalLine(terminalBody, '❌ Error: Please enter your API key', 'error');
        return;
      }
      if (!query) {
        addTerminalLine(terminalBody, '❌ Error: Please enter a claim to verify', 'error');
        return;
      }

      addTerminalLine(terminalBody, `🔍 Initializing PROOF-AI fact-check...`, 'info');
      addTerminalLine(terminalBody, `   Provider: ${provider}`, 'info');
      if (model) addTerminalLine(terminalBody, `   Model: ${model}`, 'info');

      try {
        const response = await fetch('/api/fact-check', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            api_key: apiKey,
            provider: provider,
            model: model,
            query: query,
            stream: true
          })
        });

        if (!response.ok) {
          const err = await response.json().catch(() => ({ detail: 'Unknown error' }));
          throw new Error(err.detail || `HTTP ${response.status}`);
        }

        addTerminalLine(terminalBody, `✅ Connected. Streaming verdicts...`, 'info');

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split('\n\n');
          buffer = lines.pop(); // Keep incomplete line in buffer

          for (const line of lines) {
            if (line.startsWith('data: ')) {
              try {
                const data = JSON.parse(line.slice(6));

                if (data.event === 'error') {
                  addTerminalLine(terminalBody, `❌ Error: ${data.message}`, 'error');
                  break;
                }

                if (data.event === 'claims_extracted') {
                  addTerminalLine(terminalBody, `   Extracted ${data.count} claim(s)`, 'info');
                }

                if (data.event === 'verdict') {
                  const icon = data.verdict === 'VERIFIED' ? '✅' :
                              data.verdict === 'BLOCKED' ? '🚫' :
                              data.verdict === 'CONFLICT' ? '⚡' : '⚠️';
                  addTerminalLine(terminalBody, `\n${icon} [${data.verdict}] conf: ${data.confidence.toFixed(2)}`, 'info');
                  addTerminalLine(terminalBody, `   Claim: ${data.claim.substring(0, 80)}${data.claim.length > 80 ? '...' : ''}`, 'info');
                  addTerminalLine(terminalBody, `   Hallucination: ${data.halluc_type}`, 'info');
                  if (data.explanation) {
                    addTerminalLine(terminalBody, `   ↳ ${data.explanation}`, 'info');
                  }
                }

                if (data.event === 'complete') {
                  addTerminalLine(terminalBody, `\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━`, 'info');
                  addTerminalLine(terminalBody, `📊 Summary: ${data.verified} verified, ${data.blocked} blocked, ${data.conflicts} conflicts`, 'info');
                  addTerminalLine(terminalBody, `   Hallucination rate: ${(data.halluc_rate * 100).toFixed(1)}%`, 'info');
                  addTerminalLine(terminalBody, `   Types: ${data.halluc_types.join(', ') || 'none'}`, 'info');
                  addTerminalLine(terminalBody, `   Latency: ${data.latency_ms.toFixed(1)}ms`, 'info');
                  addTerminalLine(terminalBody, `━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━`, 'info');
                }
              } catch (parseErr) {
                console.error('Parse error:', parseErr, line);
              }
            }
          }
        }

      } catch (err) {
        addTerminalLine(terminalBody, `❌ Request failed: ${err.message}`, 'error');
        addTerminalLine(terminalBody, `   Check your API key and try again.`, 'error');
      }
    });
  }

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
