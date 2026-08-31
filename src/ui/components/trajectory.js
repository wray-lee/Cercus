// Trajectory canvas renderer for NiceGUI Vue component.
// Called via window.cercusTraj(data) from Python.
// Ported from v1.0.0 index.html — uses sizeCanvas pattern.

(function(){
  const lastSigs = {};

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

  window.cercusTraj = function(data) {
    const cv = document.getElementById(data.canvasId);
    if (!cv) return;

    // sizeCanvas BEFORE signature check — resize must happen even when data is unchanged
    const ctx = cv.getContext('2d');
    const { dpr, sx, sy } = sizeCanvas(cv, 150, 150);

    const pts = data.trail_points || [];
    const angle = data.angle || 0;
    const first = pts.length ? pts[0] : [0,0];
    const last = pts.length ? pts[pts.length-1] : [0,0];
    const sig = pts.length + '|' + first[0] + '|' + first[1] + '|' + last[0] + '|' + last[1] + '|' + angle
              + '|' + (data.min_x||0) + '|' + (data.max_x||0) + '|' + (data.min_y||0) + '|' + (data.max_y||0)
              + '|' + cv.width + '|' + cv.height;
    if (sig === lastSigs[data.canvasId]) return;
    lastSigs[data.canvasId] = sig;
    ctx.setTransform(dpr * sx, 0, 0, dpr * sy, 0, 0);
    ctx.fillStyle = '#000';
    ctx.fillRect(0, 0, 150, 150);

    const W = 150, H = 150;

    let dec = pts;
    if (pts.length > 200) {
      const step = Math.ceil(pts.length / 200);
      dec = pts.filter((_, i) => i % step === 0);
      if (dec[dec.length - 1] !== pts[pts.length - 1]) dec.push(pts[pts.length - 1]);
    }
    if (dec.length < 2) {
      // Draw arrow at center even with no trail
      if (angle !== 0 || pts.length > 0) {
        _drawArrow(ctx, W/2, H/2, angle);
      }
      return;
    }

    const minx = data.min_x, maxx = data.max_x, miny = data.min_y, maxy = data.max_y;
    if (!Number.isFinite(minx) || !Number.isFinite(maxx) || !Number.isFinite(miny) || !Number.isFinite(maxy)) return;

    const PAD = 10;
    const mx = Math.max((maxx - minx) * 0.1, 0.5), my = Math.max((maxy - miny) * 0.1, 0.5);
    const x0 = minx - mx, x1 = maxx + mx, y0 = miny - my, y1 = maxy + my;
    const rx = Math.max(x1 - x0, 10), ry = Math.max(y1 - y0, 10);
    const scale = Math.min((W - 2 * PAD) / rx, (H - 2 * PAD) / ry);
    const cx = (x0 + x1) / 2, cy = (y0 + y1) / 2, cxC = W / 2, cyC = H / 2;

    const flat = [];
    for (const [px, py] of dec) flat.push([cxC + (px - cx) * scale, cyC - (py - cy) * scale]);
    ctx.strokeStyle = '#22D3EE'; ctx.lineWidth = 2; ctx.lineJoin = 'round'; ctx.lineCap = 'round';
    ctx.beginPath(); ctx.moveTo(flat[0][0], flat[0][1]);
    for (let i = 1; i < flat.length; i++) ctx.lineTo(flat[i][0], flat[i][1]);
    ctx.stroke();

    // Arrow at last point
    const lastPt = pts[pts.length - 1];
    const lx = cxC + (lastPt[0] - cx) * scale;
    const ly = cyC - (lastPt[1] - cy) * scale;
    _drawArrow(ctx, lx, ly, angle);
  };

  function _drawArrow(ctx, lx, ly, angle) {
    const rad = (angle || 0) * Math.PI / 180;
    const dx = -Math.sin(rad), dy = Math.cos(rad);
    const rx2 = Math.cos(rad), ry2 = Math.sin(rad);
    const cdx = dx, cdy = -dy, crx = rx2, cry = -ry2;
    const L = 6, B = 5, Wd = 4, N = 2;
    const tip = [lx + cdx * L, ly + cdy * L];
    const br = [lx - cdx * B + crx * Wd, ly - cdy * B + cry * Wd];
    const notch = [lx - cdx * N, ly - cdy * N];
    const bl = [lx - cdx * B - crx * Wd, ly - cdy * B - cry * Wd];
    ctx.fillStyle = '#fff'; ctx.strokeStyle = '#22D3EE'; ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(tip[0], tip[1]); ctx.lineTo(br[0], br[1]);
    ctx.lineTo(notch[0], notch[1]); ctx.lineTo(bl[0], bl[1]); ctx.closePath();
    ctx.fill(); ctx.stroke();
  }
})();
