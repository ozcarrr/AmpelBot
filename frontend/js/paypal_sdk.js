/**
 * PayPal JS SDK Integration & Checkout Controller for AmpelBot.
 * Handles dynamic SDK script injection, PayPal Smart Buttons rendering,
 * and direct Sandbox Orders V2 capture execution.
 */

const PayPalSDKManager = {
  isLoaded: false,
  clientId: null,
  currency: 'USD',
  loadPromise: null,

  async init() {
    if (this.loadPromise) return this.loadPromise;

    this.loadPromise = (async () => {
      try {
        const res = await fetch('/api/config/public');
        if (!res.ok) throw new Error(`Config fetch failed with HTTP ${res.status}`);
        const config = await res.json();

        this.clientId = config.paypal_client_id || 'sb';
        this.currency = config.currency || 'USD';

        await this._injectSDKScript(this.clientId, this.currency);
        this.isLoaded = true;
        return true;
      } catch (err) {
        console.warn('PayPal SDK dynamic injection unavailable. Direct capture enabled:', err);
        return false;
      }
    })();

    return this.loadPromise;
  },

  _injectSDKScript(clientId, currency) {
    return new Promise((resolve, reject) => {
      if (document.getElementById('paypal-js-sdk')) {
        return resolve();
      }

      const script = document.createElement('script');
      script.id = 'paypal-js-sdk';
      script.src = `https://www.paypal.com/sdk/js?client-id=${clientId}&currency=${currency}&components=buttons`;
      script.async = true;
      script.onload = () => resolve();
      script.onerror = () => reject(new Error('Failed to load PayPal JS SDK script.'));

      document.head.appendChild(script);
    });
  },

  async renderButtons({
    containerId = 'paypal-button-container',
    sku,
    negotiated_price,
    deal_token = null,
    session_id = null,
    onSuccess,
    onError,
  }) {
    const container = document.getElementById(containerId);
    if (!container) return;

    container.innerHTML = '';
    await this.init();

    if (!window.paypal || !window.paypal.Buttons) {
      container.innerHTML = `
        <div class="text-xs font-mono text-amber-400 bg-amber-950/40 p-2 rounded border border-amber-800/50 mb-2">
          PayPal Smart Button blocked by browser sandbox. Use Direct Sandbox Capture.
        </div>
      `;
      return;
    }

    try {
      window.paypal.Buttons({
        style: {
          layout: 'vertical',
          color: 'gold',
          shape: 'rect',
          label: 'paypal',
          height: 40,
        },

        createOrder: async () => {
          const payload = {
            sku: sku,
            negotiated_price: parseFloat(negotiated_price),
            deal_token: deal_token,
            session_id: session_id,
            buyer_notes: 'Created via AmpelBot checkout',
          };

          const response = await fetch('/api/orders/create', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
          });

          if (!response.ok) {
            const errData = await response.json();
            throw new Error(errData.detail?.message || errData.detail || 'Order creation failed');
          }

          const order = await response.json();
          return order.order_id;
        },

        onApprove: async (data) => {
          try {
            const captureRes = await fetch(`/api/orders/${data.orderID}/capture`, {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
            });

            if (!captureRes.ok) {
              const err = await captureRes.json();
              throw new Error(err.detail?.message || 'Capture failed');
            }

            const captureData = await captureRes.json();
            if (onSuccess) onSuccess(captureData);
          } catch (err) {
            if (onError) onError(err);
          }
        },

        onError: (err) => {
          if (onError) onError(err);
        },
      }).render(`#${containerId}`);

    } catch (err) {
      if (onError) onError(err);
    }
  },

  async simulateInstantCheckout({ sku, negotiated_price, deal_token, session_id }) {
    const createRes = await fetch('/api/orders/create', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        sku: sku,
        negotiated_price: parseFloat(negotiated_price),
        deal_token: deal_token,
        session_id: session_id,
        buyer_notes: 'Direct Orders V2 capture verification',
      }),
    });

    if (!createRes.ok) {
      const err = await createRes.json();
      throw new Error(err.detail?.message || err.detail || 'Failed to create PayPal order');
    }

    const orderData = await createRes.json();

    const captureRes = await fetch(`/api/orders/${orderData.order_id}/capture`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
    });

    if (!captureRes.ok) {
      const err = await captureRes.json();
      throw new Error(err.detail?.message || 'Failed to capture PayPal order');
    }

    const captureData = await captureRes.json();
    return { order: orderData, capture: captureData };
  },
};

window.PayPalSDKManager = PayPalSDKManager;
