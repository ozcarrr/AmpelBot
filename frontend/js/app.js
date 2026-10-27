/**
 * AmpelBot Frontend Application Controller
 * Coordinates product catalog selection, negotiation state machine,
 * telemetry grid binding, and PayPal Orders V2 checkout execution.
 */

const AppState = {
  sessionId: `session_${Date.now()}_${Math.random().toString(36).substring(2, 8)}`,
  selectedSku: 'AMP-01',
  selectedProduct: null,
  products: [],
  currentTrafficLight: 'YELLOW',
  dealLocked: false,
  agreedPrice: null,
  dealToken: null,
  bundledSkus: null,
  isSending: false,
  gridApi: null,
};

const DOM = {
  productsGrid: document.getElementById('products-grid'),
  selectedProductTitle: document.getElementById('selected-product-title'),
  selectedProductSku: document.getElementById('selected-product-sku'),
  selectedProductRetail: document.getElementById('selected-product-retail'),
  bundleActiveBadge: document.getElementById('bundle-active-badge'),
  ampelHousing: document.getElementById('ampel-housing'),
  ampelStatusBadge: document.getElementById('ampel-status-badge'),
  chatTranscript: document.getElementById('chat-transcript'),
  chatInput: document.getElementById('chat-input'),
  chatForm: document.getElementById('chat-form'),
  sendBtn: document.getElementById('send-btn'),
  dealUnlockedCard: document.getElementById('deal-unlocked-card'),
  dealPriceDisplay: document.getElementById('deal-price-display'),
  dealSavingsDisplay: document.getElementById('deal-savings-display'),
  dealTokenDisplay: document.getElementById('deal-token-display'),
  paypalBtnContainer: document.getElementById('paypal-button-container'),
  instantCheckoutBtn: document.getElementById('instant-checkout-btn'),
  receiptModal: document.getElementById('receipt-modal'),
  receiptDetails: document.getElementById('receipt-details'),
  closeReceiptBtn: document.getElementById('close-receipt-btn'),
  resetChatBtn: document.getElementById('reset-chat-btn'),
  refreshTelemetryBtn: document.getElementById('refresh-telemetry-btn'),
  seedDemoTelemetryBtn: document.getElementById('seed-demo-telemetry-btn'),
  kpiGmv: document.getElementById('kpi-gmv'),
  kpiMarginRetained: document.getElementById('kpi-margin-retained'),
  kpiMarginSubtext: document.getElementById('kpi-margin-subtext'),
  kpiFunnel: document.getElementById('kpi-conversion-funnel'),
  kpiFunnelSubtext: document.getElementById('kpi-funnel-subtext'),
  kpiSecurityInterventions: document.getElementById('kpi-security-interventions'),
  llmProviderBadge: document.getElementById('llm-provider-badge'),
  paypalConfigBadge: document.getElementById('paypal-config-badge'),
};

async function initApp() {
  await loadPublicConfig();
  await loadProductsCatalog();
  initAGGridTelemetry();
  await loadTelemetryData();
  setupEventListeners();

  if (window.PayPalSDKManager) {
    window.PayPalSDKManager.init();
  }
}

async function loadPublicConfig() {
  try {
    const res = await fetch('/api/config/public');
    if (!res.ok) return;
    const config = await res.json();
    if (DOM.llmProviderBadge) {
      DOM.llmProviderBadge.textContent = `LLM: ${config.llm_provider.toUpperCase()}`;
    }
    if (DOM.paypalConfigBadge) {
      DOM.paypalConfigBadge.textContent = config.is_paypal_configured ? 'PayPal: Live Sandbox' : 'PayPal: Sandbox Mock';
    }
  } catch (err) {
    console.warn('Could not load public config:', err);
  }
}

async function loadProductsCatalog() {
  try {
    const res = await fetch('/api/products');
    if (!res.ok) throw new Error('Catalog fetch failed');
    AppState.products = await res.json();
  } catch (err) {
    AppState.products = [
      {
        sku: 'AMP-01',
        name: 'Custom CNC 75% Aluminum Mechanical Keyboard Kit',
        description: 'Anodized 6063 aluminum chassis, FR4 gasket mount plate, hot-swappable PCB.',
        retail_price: 180.00,
        category: 'Hardware',
        in_stock: true,
      },
      {
        sku: 'AMP-02',
        name: 'Vintage 2008 European Final Football Kit',
        description: 'Reproduction of the Moscow 2008 European Final long-sleeve kit.',
        retail_price: 95.00,
        category: 'Apparel',
        in_stock: true,
      },
      {
        sku: 'AMP-03',
        name: 'DevSecOps Self-Hosted Lab Automation Bundle',
        description: 'Terraform, Ansible, and Kubernetes recipes for automated CI/CD and deployment.',
        retail_price: 49.00,
        category: 'Software / Digital',
        in_stock: true,
      },
    ];
  }

  renderProductsGrid();
  selectProduct(AppState.selectedSku);
}

function renderProductsGrid() {
  if (!DOM.productsGrid) return;

  DOM.productsGrid.innerHTML = AppState.products.map(p => {
    const isSelected = p.sku === AppState.selectedSku;
    const borderClass = isSelected ? 'border-blue-500 ring-1 ring-blue-500/30' : 'border-slate-800 hover:border-slate-700';

    return `
      <div class="glass-panel p-4 rounded-lg ${borderClass} transition-colors flex flex-col justify-between" id="card-${p.sku}">
        <div>
          <div class="flex items-center justify-between mb-2">
            <span class="text-xs font-mono px-2 py-0.5 rounded bg-slate-900 text-blue-400 border border-slate-800 font-bold">
              ${p.sku}
            </span>
            <span class="text-[11px] font-mono px-2 py-0.5 rounded bg-slate-900 text-slate-400 border border-slate-800">
              ${p.category}
            </span>
          </div>
          <h3 class="text-sm font-bold text-white mb-1 leading-snug">${p.name}</h3>
          <p class="text-xs text-slate-400 mb-3 line-clamp-2">${p.description}</p>
        </div>

        <div>
          <div class="flex items-baseline justify-between pt-2.5 border-t border-slate-800 mb-3 font-mono">
            <div>
              <span class="text-[10px] text-slate-400 uppercase block">List Price</span>
              <span class="text-base font-bold text-white">$${p.retail_price.toFixed(2)}</span>
            </div>
            <div class="text-right">
              <span class="text-[11px] text-emerald-400 bg-emerald-950/60 border border-emerald-800/40 px-2 py-0.5 rounded">
                Negotiable
              </span>
            </div>
          </div>

          <div class="grid grid-cols-2 gap-2 font-mono text-xs">
            <button 
              onclick="buyAtRetail('${p.sku}')"
              class="w-full py-1.5 px-3 rounded bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 transition font-medium">
              Buy Retail
            </button>
            <button 
              onclick="selectProduct('${p.sku}')"
              class="w-full py-1.5 px-3 rounded bg-blue-600 hover:bg-blue-500 text-white transition font-medium">
              Negotiate
            </button>
          </div>
        </div>
      </div>
    `;
  }).join('');
}

function selectProduct(sku) {
  AppState.selectedSku = sku;
  AppState.selectedProduct = AppState.products.find(p => p.sku === sku) || AppState.products[0];

  AppState.products.forEach(p => {
    const card = document.getElementById(`card-${p.sku}`);
    if (!card) return;
    const isSelected = p.sku === sku;
    card.classList.toggle('border-blue-500', isSelected);
    card.classList.toggle('ring-1', isSelected);
    card.classList.toggle('ring-blue-500/30', isSelected);
    card.classList.toggle('border-slate-800', !isSelected);
  });

  if (DOM.selectedProductTitle) DOM.selectedProductTitle.textContent = AppState.selectedProduct.name;
  if (DOM.selectedProductSku) DOM.selectedProductSku.textContent = AppState.selectedProduct.sku;
  if (DOM.selectedProductRetail) DOM.selectedProductRetail.textContent = `$${AppState.selectedProduct.retail_price.toFixed(2)}`;

  resetConversation(false);
}

function setTrafficLight(state) {
  AppState.currentTrafficLight = state;
  if (!DOM.ampelHousing) return;

  DOM.ampelHousing.classList.remove('ampel-active-red', 'ampel-active-yellow', 'ampel-active-green');

  if (state === 'RED') {
    DOM.ampelHousing.classList.add('ampel-active-red');
    if (DOM.ampelStatusBadge) {
      DOM.ampelStatusBadge.className = 'px-2 py-0.5 rounded text-xs font-mono font-bold bg-red-950/80 border border-red-600 text-red-300';
      DOM.ampelStatusBadge.textContent = 'STATE: RED';
    }
    return;
  }

  if (state === 'GREEN') {
    DOM.ampelHousing.classList.add('ampel-active-green');
    if (DOM.ampelStatusBadge) {
      DOM.ampelStatusBadge.className = 'px-2 py-0.5 rounded text-xs font-mono font-bold bg-emerald-950/80 border border-emerald-500 text-emerald-300';
      DOM.ampelStatusBadge.textContent = 'STATE: GREEN';
    }
    return;
  }

  DOM.ampelHousing.classList.add('ampel-active-yellow');
  if (DOM.ampelStatusBadge) {
    DOM.ampelStatusBadge.className = 'px-2 py-0.5 rounded text-xs font-mono font-bold bg-amber-950/80 border border-amber-600 text-amber-300';
    DOM.ampelStatusBadge.textContent = 'STATE: YELLOW';
  }
}

function appendMessage({ role, content, trafficLight, reasoningSummary, agreedPrice, counterPrice }) {
  if (!DOM.chatTranscript) return;

  const isUser = role === 'user';
  const bubbleWrapper = document.createElement('div');
  bubbleWrapper.className = `flex gap-2.5 mb-3 ${isUser ? 'justify-end' : 'justify-start'}`;

  if (isUser) {
    bubbleWrapper.innerHTML = `
      <div class="max-w-[80%] bg-blue-600/90 text-white rounded p-3 text-xs leading-relaxed font-sans">
        ${escapeHtml(content)}
      </div>
      <div class="w-7 h-7 rounded bg-slate-800 border border-slate-700 flex items-center justify-center text-[10px] font-mono text-slate-300 flex-shrink-0">
        USER
      </div>
    `;
  } else {
    let pricePill = '';
    if (trafficLight === 'GREEN' && agreedPrice) {
      pricePill = `
        <div class="mt-2 text-xs font-mono bg-emerald-950/60 border border-emerald-700 text-emerald-300 px-2.5 py-1 rounded flex items-center justify-between">
          <span>Agreed Price:</span>
          <span class="font-bold text-emerald-200">$${agreedPrice.toFixed(2)}</span>
        </div>
      `;
    } else if (counterPrice) {
      pricePill = `
        <div class="mt-2 text-xs font-mono bg-amber-950/60 border border-amber-700 text-amber-300 px-2.5 py-1 rounded flex items-center justify-between">
          <span>Counter-Offer:</span>
          <span class="font-bold text-amber-200">$${counterPrice.toFixed(2)}</span>
        </div>
      `;
    }

    let reasoningBox = '';
    if (reasoningSummary) {
      const isFirewall = reasoningSummary.includes('[SECURITY') || reasoningSummary.includes('[GUARDRAIL');
      const badgeClass = isFirewall ? 'text-red-400 bg-red-950/60 border-red-800' : 'text-slate-400 bg-slate-900 border-slate-800';
      reasoningBox = `
        <div class="mt-2 text-[11px] font-mono px-2 py-1 rounded border ${badgeClass} flex items-start gap-1.5">
          <span class="font-bold flex-shrink-0">${isFirewall ? 'GUARD:' : 'MODEL:'}</span>
          <span class="leading-tight">${escapeHtml(reasoningSummary)}</span>
        </div>
      `;
    }

    bubbleWrapper.innerHTML = `
      <div class="w-7 h-7 rounded bg-slate-800 border border-slate-700 flex items-center justify-center text-[10px] font-mono text-blue-400 flex-shrink-0">
        BOT
      </div>
      <div class="max-w-[85%] bg-slate-900 text-slate-200 border border-slate-800 rounded p-3 text-xs leading-relaxed">
        <div class="flex items-center justify-between gap-2 mb-1">
          <span class="text-[11px] font-mono font-bold text-slate-400 uppercase">AmpelBot</span>
          <span class="text-[10px] font-mono px-1.5 py-0.2 rounded ${trafficLight === 'GREEN' ? 'bg-emerald-950 text-emerald-400 border border-emerald-800' : trafficLight === 'RED' ? 'bg-red-950 text-red-400 border border-red-800' : 'bg-amber-950 text-amber-400 border border-amber-800'}">
            ${trafficLight || 'INFO'}
          </span>
        </div>
        <p class="text-xs text-slate-200 font-sans">${escapeHtml(content)}</p>
        ${pricePill}
        ${reasoningBox}
      </div>
    `;
  }

  DOM.chatTranscript.appendChild(bubbleWrapper);
  DOM.chatTranscript.scrollTop = DOM.chatTranscript.scrollHeight;
}

async function handleSendMessage(userText) {
  const text = (userText || DOM.chatInput.value).trim();
  if (!text || AppState.isSending) return;

  AppState.isSending = true;
  if (DOM.sendBtn) DOM.sendBtn.disabled = true;
  if (DOM.chatInput) DOM.chatInput.value = '';

  appendMessage({ role: 'user', content: text });

  const typingIndicator = document.createElement('div');
  typingIndicator.id = 'typing-indicator';
  typingIndicator.className = 'flex gap-2.5 mb-3';
  typingIndicator.innerHTML = `
    <div class="w-7 h-7 rounded bg-slate-800 border border-slate-700 flex items-center justify-center text-[10px] font-mono text-blue-400">BOT</div>
    <div class="bg-slate-900 border border-slate-800 rounded px-3 py-2 text-xs font-mono text-slate-400">
      Evaluating offer...
    </div>
  `;
  DOM.chatTranscript.appendChild(typingIndicator);
  DOM.chatTranscript.scrollTop = DOM.chatTranscript.scrollHeight;

  try {
    const payload = {
      session_id: AppState.sessionId,
      sku: AppState.selectedSku,
      user_message: text,
    };

    const res = await fetch('/api/chat/message', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });

    if (typingIndicator.parentNode) {
      typingIndicator.parentNode.removeChild(typingIndicator);
    }

    if (!res.ok) {
      const errData = await res.json();
      throw new Error(errData.detail?.message || errData.detail || 'Negotiation request failed');
    }

    const data = await res.json();
    setTrafficLight(data.traffic_light);

    if (data.bundled_skus && data.bundled_skus.length > 1) {
      AppState.bundledSkus = data.bundled_skus;
      if (DOM.bundleActiveBadge) {
        DOM.bundleActiveBadge.classList.remove('hidden');
        DOM.bundleActiveBadge.textContent = `BUNDLE: ${data.bundled_skus.join(' + ')}`;
      }
    }

    appendMessage({
      role: 'assistant',
      content: data.reply_message,
      trafficLight: data.traffic_light,
      reasoningSummary: data.reasoning_summary,
      agreedPrice: data.agreed_price,
      counterPrice: data.counter_offer_price,
    });

    if (data.traffic_light === 'GREEN' && data.agreed_price) {
      AppState.dealLocked = true;
      AppState.agreedPrice = data.agreed_price;
      AppState.dealToken = data.deal_token;
      showDealUnlockedCard(data.agreed_price, data.deal_token, data.bundled_skus);
    }

    loadTelemetryData();

  } catch (err) {
    if (typingIndicator.parentNode) typingIndicator.parentNode.removeChild(typingIndicator);
    appendMessage({
      role: 'assistant',
      content: `System exception: ${err.message}`,
      trafficLight: 'RED',
      reasoningSummary: 'Network error or unhandled backend exception.',
    });
  } finally {
    AppState.isSending = false;
    if (DOM.sendBtn) DOM.sendBtn.disabled = false;
    if (DOM.chatInput) DOM.chatInput.focus();
  }
}

function showDealUnlockedCard(agreedPrice, dealToken, bundledSkus = null) {
  if (!DOM.dealUnlockedCard) return;

  const activeBundle = bundledSkus || AppState.bundledSkus;
  const isBundle = activeBundle && activeBundle.length > 1;

  let retail = AppState.selectedProduct ? AppState.selectedProduct.retail_price : agreedPrice;
  if (isBundle) {
    const bundleProds = activeBundle.map(s => AppState.products.find(p => p.sku === s)).filter(Boolean);
    if (bundleProds.length > 0) {
      retail = bundleProds.reduce((sum, p) => sum + p.retail_price, 0);
    }
  }

  const savings = Math.max(0, retail - agreedPrice);
  const savingsPct = retail > 0 ? ((savings / retail) * 100).toFixed(1) : '0.0';

  if (DOM.dealPriceDisplay) DOM.dealPriceDisplay.textContent = `$${agreedPrice.toFixed(2)}`;
  if (DOM.dealSavingsDisplay) {
    DOM.dealSavingsDisplay.textContent = isBundle
      ? `Bundle Concession: -$${savings.toFixed(2)} (-${savingsPct}% vs $${retail.toFixed(2)} composite list)`
      : `Variance: -$${savings.toFixed(2)} (-${savingsPct}% vs list)`;
  }
  if (DOM.dealTokenDisplay) {
    DOM.dealTokenDisplay.textContent = dealToken ? `${dealToken.substring(0, 36)}...` : 'Session verified';
  }

  const checkoutSku = isBundle ? activeBundle.slice().sort().join('+') : AppState.selectedSku;

  DOM.dealUnlockedCard.classList.remove('hidden');

  if (window.PayPalSDKManager) {
    window.PayPalSDKManager.renderButtons({
      containerId: 'paypal-button-container',
      sku: checkoutSku,
      bundled_skus: isBundle ? activeBundle : null,
      negotiated_price: agreedPrice,
      deal_token: dealToken,
      session_id: AppState.sessionId,
      onSuccess: (captureData) => showReceiptModal(captureData),
      onError: (err) => alert(`PayPal Error: ${err.message}`),
    });
  }

  if (DOM.instantCheckoutBtn) {
    DOM.instantCheckoutBtn.onclick = async () => {
      DOM.instantCheckoutBtn.disabled = true;
      DOM.instantCheckoutBtn.textContent = 'Executing Orders V2 Capture...';

      try {
        const result = await window.PayPalSDKManager.simulateInstantCheckout({
          sku: checkoutSku,
          bundled_skus: isBundle ? activeBundle : null,
          negotiated_price: agreedPrice,
          deal_token: dealToken,
          session_id: AppState.sessionId,
        });
        showReceiptModal(result.capture, result.order);
      } catch (err) {
        alert(`Checkout simulation failed: ${err.message}`);
      } finally {
        DOM.instantCheckoutBtn.disabled = false;
        DOM.instantCheckoutBtn.textContent = 'Execute Direct Sandbox Capture';
      }
    };
  }
}
        showReceiptModal(result.capture, result.order);
      } catch (err) {
        alert(`Checkout simulation failed: ${err.message}`);
      } finally {
        DOM.instantCheckoutBtn.disabled = false;
        DOM.instantCheckoutBtn.textContent = 'Execute Direct Sandbox Capture';
      }
    };
  }
}

function buyAtRetail(sku) {
  selectProduct(sku);
  const retail = AppState.selectedProduct.retail_price;
  AppState.agreedPrice = retail;
  AppState.dealLocked = true;
  AppState.dealToken = null;

  setTrafficLight('GREEN');
  appendMessage({
    role: 'assistant',
    content: `Standard retail price $${retail.toFixed(2)} selected. Checkout authorized.`,
    trafficLight: 'GREEN',
    reasoningSummary: 'Buyer accepted standard retail catalog price.',
    agreedPrice: retail,
  });

  showDealUnlockedCard(retail, null);
}

function showReceiptModal(captureData, orderData = null) {
  if (!DOM.receiptModal || !DOM.receiptDetails) return;

  DOM.receiptDetails.innerHTML = `
    <div class="space-y-2 font-mono text-xs">
      <div class="flex justify-between border-b border-slate-800 pb-1.5">
        <span class="text-slate-400">Order ID:</span>
        <span class="text-white font-bold">${captureData.order_id || (orderData && orderData.order_id)}</span>
      </div>
      <div class="flex justify-between border-b border-slate-800 pb-1.5">
        <span class="text-slate-400">Status:</span>
        <span class="text-emerald-400 font-bold">${captureData.status || 'COMPLETED'}</span>
      </div>
      <div class="flex justify-between border-b border-slate-800 pb-1.5">
        <span class="text-slate-400">SKU:</span>
        <span class="text-white">${AppState.selectedSku}</span>
      </div>
      <div class="flex justify-between border-b border-slate-800 pb-1.5">
        <span class="text-slate-400">Settled Amount:</span>
        <span class="text-emerald-300 font-bold">
          $${(captureData.amount_captured || AppState.agreedPrice).toFixed(2)} ${captureData.currency || 'USD'}
        </span>
      </div>
      <div class="flex justify-between border-b border-slate-800 pb-1.5">
        <span class="text-slate-400">Capture ID:</span>
        <span class="text-slate-300">${captureData.capture_id || 'CAP-' + Math.random().toString(36).substring(2, 10).toUpperCase()}</span>
      </div>
      <div class="flex justify-between">
        <span class="text-slate-400">Timestamp:</span>
        <span class="text-slate-400">${new Date(captureData.captured_at || Date.now()).toISOString()}</span>
      </div>
    </div>
  `;

  DOM.receiptModal.classList.remove('hidden');
}

function resetConversation(resetSessionId = true) {
  if (resetSessionId) {
    AppState.sessionId = `session_${Date.now()}_${Math.random().toString(36).substring(2, 8)}`;
  }
  AppState.dealLocked = false;
  AppState.agreedPrice = null;
  AppState.dealToken = null;
  AppState.bundledSkus = null;
  if (DOM.bundleActiveBadge) DOM.bundleActiveBadge.classList.add('hidden');

  setTrafficLight('YELLOW');

  if (DOM.dealUnlockedCard) DOM.dealUnlockedCard.classList.add('hidden');
  if (!DOM.chatTranscript) return;

  DOM.chatTranscript.innerHTML = '';
  const initialGreeting = `AmpelBot initialized for ${AppState.selectedProduct ? AppState.selectedProduct.name : 'product'}. Standard list price: $${AppState.selectedProduct ? AppState.selectedProduct.retail_price.toFixed(2) : '0.00'}. Submit an offer to begin negotiation.`;
  appendMessage({
    role: 'assistant',
    content: initialGreeting,
    trafficLight: 'YELLOW',
    reasoningSummary: 'Session initialized. Awaiting buyer opening offer.',
  });
}

function initAGGridTelemetry() {
  const gridDiv = document.getElementById('ag-grid-telemetry');
  if (!gridDiv || !window.agGrid) return;

  const columnDefs = [
    {
      headerName: 'Event ID',
      field: 'id',
      width: 120,
      cellClass: 'font-mono text-xs text-blue-400',
    },
    {
      headerName: 'Timestamp',
      field: 'timestamp',
      width: 110,
      valueFormatter: params => {
        try {
          return new Date(params.value).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
        } catch (e) {
          return params.value;
        }
      },
      cellClass: 'font-mono text-xs text-slate-400',
    },
    {
      headerName: 'SKU',
      field: 'sku',
      width: 95,
      cellClass: 'font-mono text-xs text-white',
    },
    {
      headerName: 'State',
      field: 'traffic_light',
      width: 110,
      cellRenderer: params => {
        const val = params.value;
        if (val === 'GREEN') {
          return `<span class="px-2 py-0.5 rounded text-[11px] font-mono font-semibold bg-emerald-950 text-emerald-400 border border-emerald-800">GREEN</span>`;
        }
        if (val === 'RED') {
          return `<span class="px-2 py-0.5 rounded text-[11px] font-mono font-semibold bg-red-950 text-red-400 border border-red-800">RED</span>`;
        }
        return `<span class="px-2 py-0.5 rounded text-[11px] font-mono font-semibold bg-amber-950 text-amber-400 border border-amber-800">YELLOW</span>`;
      },
    },
    {
      headerName: 'Retail Price',
      field: 'retail_price',
      width: 105,
      valueFormatter: params => params.value ? `$${params.value.toFixed(2)}` : '—',
      cellClass: 'font-mono text-xs text-slate-300',
    },
    {
      headerName: 'Buyer Offer',
      field: 'buyer_offer',
      width: 110,
      valueFormatter: params => params.value ? `$${params.value.toFixed(2)}` : '—',
      cellClass: 'font-mono text-xs text-amber-300',
    },
    {
      headerName: 'Settled / Counter',
      field: 'final_price',
      width: 130,
      valueFormatter: params => params.value ? `$${params.value.toFixed(2)}` : '—',
      cellClass: 'font-mono text-xs font-bold text-white',
    },
    {
      headerName: 'Variance %',
      field: 'discount_pct',
      width: 105,
      valueFormatter: params => params.value ? `${params.value.toFixed(1)}%` : '0%',
      cellClass: 'font-mono text-xs text-emerald-400',
    },
    {
      headerName: 'Margin Defense',
      field: 'margin_protected',
      width: 165,
      cellClass: 'font-mono text-xs text-slate-300',
    },
    {
      headerName: 'Firewall Intercept',
      field: 'firewall_triggered',
      width: 140,
      cellRenderer: params => {
        if (params.value) {
          return `<span class="px-2 py-0.5 rounded text-[11px] font-mono font-semibold bg-red-950 text-red-400 border border-red-800">INTERCEPTED</span>`;
        }
        return `<span class="px-2 py-0.5 rounded text-[11px] font-mono text-slate-400 border border-slate-700">PROTECTED</span>`;
      },
    },
    {
      headerName: 'Decision Rationale',
      field: 'reasoning_summary',
      flex: 1,
      minWidth: 260,
      cellClass: 'text-xs font-mono text-slate-300',
    },
  ];

  const gridOptions = {
    columnDefs: columnDefs,
    rowData: [],
    defaultColDef: {
      sortable: true,
      filter: true,
      resizable: true,
    },
    rowHeight: 34,
    headerHeight: 36,
    animateRows: false,
  };

  AppState.gridApi = agGrid.createGrid(gridDiv, gridOptions);
}

async function loadTelemetryData() {
  try {
    const res = await fetch('/api/merchant/telemetry');
    if (!res.ok) return;
    const data = await res.json();

    if (AppState.gridApi && data.events) {
      AppState.gridApi.setGridOption('rowData', data.events);
    }

    if (data.summary) {
      const s = data.summary;
      if (DOM.kpiGmv) DOM.kpiGmv.textContent = `$${(s.gmv_locked_captured || s.revenue_unlocked || 0).toFixed(2)}`;
      if (DOM.kpiMarginRetained) {
        DOM.kpiMarginRetained.textContent = `+$${(s.avg_margin_retained_dollars || 0).toFixed(2)}`;
      }
      if (DOM.kpiMarginSubtext) {
        DOM.kpiMarginSubtext.textContent = `${s.avg_margin_retained_pct || 0}% profit retained above floor`;
      }
      if (DOM.kpiFunnel) {
        DOM.kpiFunnel.textContent = `${s.deals_closed} / ${s.total_sessions || s.total_negotiations} Sessions`;
      }
      if (DOM.kpiFunnelSubtext) {
        DOM.kpiFunnelSubtext.textContent = `${s.conversion_rate_pct || 0}% deal closing rate`;
      }
      if (DOM.kpiSecurityInterventions) {
        DOM.kpiSecurityInterventions.textContent = `${s.security_interventions_count || s.attacks_blocked || 0} Blocked`;
      }
    }
  } catch (err) {
    console.warn('Could not load telemetry audit logs:', err);
  }
}

function setupEventListeners() {
  if (DOM.chatForm) {
    DOM.chatForm.addEventListener('submit', (e) => {
      e.preventDefault();
      handleSendMessage();
    });
  }

  document.querySelectorAll('.demo-chip').forEach(chip => {
    chip.addEventListener('click', () => {
      const promptText = chip.getAttribute('data-prompt');
      if (promptText) {
        handleSendMessage(promptText);
      }
    });
  });

  if (DOM.resetChatBtn) {
    DOM.resetChatBtn.addEventListener('click', () => resetConversation(true));
  }

  if (DOM.refreshTelemetryBtn) {
    DOM.refreshTelemetryBtn.addEventListener('click', () => loadTelemetryData());
  }

  if (DOM.seedDemoTelemetryBtn) {
    DOM.seedDemoTelemetryBtn.addEventListener('click', async () => {
      DOM.seedDemoTelemetryBtn.disabled = true;
      DOM.seedDemoTelemetryBtn.textContent = 'Seeding...';
      try {
        const res = await fetch('/api/merchant/seed-demo', { method: 'POST' });
        if (res.ok) {
          await loadTelemetryData();
        }
      } catch (err) {
        console.warn('Failed to seed demo telemetry:', err);
      } finally {
        DOM.seedDemoTelemetryBtn.disabled = false;
        DOM.seedDemoTelemetryBtn.textContent = 'Seed Demo Records';
      }
    });
  }

  if (DOM.closeReceiptBtn) {
    DOM.closeReceiptBtn.addEventListener('click', () => {
      DOM.receiptModal.classList.add('hidden');
    });
  }
}

function escapeHtml(str) {
  if (!str) return '';
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}

document.addEventListener('DOMContentLoaded', initApp);
