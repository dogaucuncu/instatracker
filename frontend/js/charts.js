/**
 * charts.js — Lightweight canvas charts (no external libraries)
 * Currently provides a follower trend sparkline for future use.
 */

const Charts = {
  /**
   * Draw a simple sparkline on a canvas element.
   * @param {HTMLCanvasElement} canvas
   * @param {number[]} data
   * @param {string} color
   */
  drawSparkline(canvas, data, color = '#C13584') {
    if (!canvas || !data || data.length < 2) return;
    const ctx = canvas.getContext('2d');
    const w = canvas.width;
    const h = canvas.height;
    const min = Math.min(...data);
    const max = Math.max(...data);
    const range = max - min || 1;

    ctx.clearRect(0, 0, w, h);

    // Gradient fill
    const grad = ctx.createLinearGradient(0, 0, 0, h);
    grad.addColorStop(0, color + '44');
    grad.addColorStop(1, color + '00');

    const xStep = w / (data.length - 1);
    const points = data.map((v, i) => ({
      x: i * xStep,
      y: h - ((v - min) / range) * (h - 8) - 4,
    }));

    // Fill area
    ctx.beginPath();
    ctx.moveTo(points[0].x, h);
    points.forEach(p => ctx.lineTo(p.x, p.y));
    ctx.lineTo(points[points.length - 1].x, h);
    ctx.closePath();
    ctx.fillStyle = grad;
    ctx.fill();

    // Line
    ctx.beginPath();
    ctx.moveTo(points[0].x, points[0].y);
    points.forEach(p => ctx.lineTo(p.x, p.y));
    ctx.strokeStyle = color;
    ctx.lineWidth = 2;
    ctx.lineJoin = 'round';
    ctx.stroke();
  },
};
