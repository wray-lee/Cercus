// Twin preview canvas renderer for NiceGUI.
// Called via window.cercusTwin(data) from Python.
// Ported from v1.0.0 index.html — uses sizeCanvas pattern.

(function(){
  function tkColor(c) {
    if (!c || c === 'None' || c === 'none') return 'transparent';
    const MAP = {white:'#fff',black:'#000',red:'#F87171',green:'#A3E635',blue:'#60A5FA',
                 cyan:'#22D3EE',yellow:'#FACC15',gray:'#71717A',orange:'#FB923C',lime:'#A3E635'};
    return MAP[c] || c;
  }

  function drawCmd(ctx, item) {
    const cmd = item.cmd, args = item.args || [], kw = item.kwargs || {};
    const width = kw.width || 1;
    if (cmd === 'create_oval') {
      const [x0,y0,x1,y1] = args;
      ctx.beginPath();
      ctx.ellipse((x0+x1)/2,(y0+y1)/2,Math.abs(x1-x0)/2,Math.abs(y1-y0)/2,0,0,Math.PI*2);
      if (kw.fill) { ctx.fillStyle = tkColor(kw.fill); ctx.fill(); }
      ctx.strokeStyle = tkColor(kw.outline||'white'); ctx.lineWidth = width; ctx.stroke();
    } else if (cmd === 'create_line') {
      ctx.beginPath(); ctx.moveTo(args[0], args[1]);
      for (let i=2; i<args.length; i+=2) ctx.lineTo(args[i], args[i+1]);
      if (kw.dash) { ctx.setLineDash(Array.isArray(kw.dash)?kw.dash:[kw.dash,kw.dash]); }
      ctx.strokeStyle = tkColor(kw.fill||'white'); ctx.lineWidth = width; ctx.stroke();
      ctx.setLineDash([]);
    }
  }

  // v1.0.0 sizeCanvas: compute pixel buffer from cssW + model aspect ratio.
  // Does NOT trust clientHeight — derives it from clientWidth.
  function sizeCanvas(cv, wModel, hModel) {
    const dpr = window.devicePixelRatio || 1;
    const cssW = cv.clientWidth || wModel;
    const cssH = Math.max(1, cssW * hModel / wModel);
    const pw = Math.round(cssW * dpr), ph = Math.round(cssH * dpr);
    if (cv.width !== pw || cv.height !== ph) { cv.width = pw; cv.height = ph; }
    return { dpr, sx: cssW / wModel, sy: cssH / hModel };
  }

  window.cercusTwin = function(data) {
    const cv = document.getElementById(data.canvasId);
    if (!cv) return;
    const ctx = cv.getContext('2d');
    const { dpr, sx, sy } = sizeCanvas(cv, 400, 150);
    ctx.setTransform(dpr * sx, 0, 0, dpr * sy, 0, 0);
    ctx.clearRect(0, 0, 400, 150);
    ctx.fillStyle = '#000'; ctx.fillRect(0, 0, 400, 150);

    const cfg = data.twin;
    if (Array.isArray(cfg)) {
      for (const item of cfg) { try { drawCmd(ctx, item); } catch(e) {} }
    } else if (cfg && typeof cfg === 'object') {
      const side = cfg.side || '—', rr = Math.max(0.02, cfg.radius_ratio || 0), r = Math.min(100, rr * 100);
      if (side === 'center' || side === 'single') {
        ctx.strokeStyle = '#fff'; ctx.lineWidth = 1; ctx.beginPath(); ctx.ellipse(200,75,r,r,0,0,Math.PI*2); ctx.stroke();
      } else {
        if (side === 'left' || side === 'both' || side === '—') {
          ctx.strokeStyle = '#fff'; ctx.lineWidth = 1; ctx.beginPath(); ctx.ellipse(100,75,r,r,0,0,Math.PI*2); ctx.stroke();
        }
        if (side === 'right' || side === 'both' || side === '—') {
          ctx.strokeStyle = '#fff'; ctx.lineWidth = 1; ctx.beginPath(); ctx.ellipse(300,75,r,r,0,0,Math.PI*2); ctx.stroke();
        }
        ctx.strokeStyle = '#333'; ctx.lineWidth = 1; ctx.setLineDash([4,2]);
        ctx.beginPath(); ctx.moveTo(200,0); ctx.lineTo(200,150); ctx.stroke(); ctx.setLineDash([]);
      }
    }
  };
})();
