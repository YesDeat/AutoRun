// app.js —— AuToRun 工作台前端（原生 JS，无框架）
(function () {
  var map = L.map("map").setView([23.05, 113.42], 15);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19, attribution: "© OpenStreetMap",
  }).addTo(map);

  var pts = [];          // 拐点 [lng, lat]（WGS-84）
  var lineLayer = null;

  map.on("click", function (e) {
    pts.push([e.latlng.lng, e.latlng.lat]);
    redraw();
  });

  function redraw() {
    if (lineLayer) map.removeLayer(lineLayer);
    if (pts.length >= 2) {
      lineLayer = L.polyline(pts.map(function (p) { return [p[1], p[0]]; }),
        { color: "#2d7ff9", weight: 4 }).addTo(map);
      map.fitBounds(lineLayer.getBounds());
    }
  }

  function sampleTrack() {
    // 标准圆形跑道（WGS-84 圆心 + 半径 140m）
    var lat = 23.05, lng = 113.42, r = 140, n = 60;
    pts = [];
    for (var i = 0; i <= n; i++) {
      var a = (2 * Math.PI * i) / n;
      pts.push([lng + (r / (111320 * Math.cos(lat * Math.PI / 180))) * Math.cos(a),
                lat + (r / 111320) * Math.sin(a)]);
    }
    redraw();
  }

  function params() {
    return {
      points: pts,
      target_km: parseFloat(document.getElementById("km").value) || 2.0,
      pace_s_per_km: parseFloat(document.getElementById("pace").value) || 330,
      sample_interval_s: 1.0,
      speed_jitter: 0.08,
      loop_mode: "repeat",
      run_type: parseInt(document.getElementById("runType").value, 10),
      crs: document.getElementById("crs").value,
      start_face: document.getElementById("faces").value === "1",
      end_face: document.getElementById("faces").value === "1",
      middle_faces: document.getElementById("faces").value === "1" ? [0.3, 0.7] : [],
      sex: document.getElementById("sex").value,
      pause_count: 0,
    };
  }

  function showMetrics(g) {
    var m = g.metrics, v = g.validity;
    document.getElementById("metrics").innerHTML =
      "距离 " + m.distance_m + " m / " + m.point_count + " 点 / 用时 " + m.elapsed_s + " s<br>" +
      "合格: " + (v.qualified ? "是" : "否") + "；人脸点 " + g.faces.length + " 个";
    // 在地图上画生成的轨迹线
    if (lineLayer) map.removeLayer(lineLayer);
    var ll = g.line.map(function (p) { return [p[1], p[0]]; });
    lineLayer = L.polyline(ll, { color: "#c0341d", weight: 3, dashArray: "5,5" }).addTo(map);
    map.fitBounds(lineLayer.getBounds());
  }

  function showSteps(r) {
    var box = document.getElementById("steps");
    box.innerHTML = "";
    (r.steps || []).forEach(function (s) {
      var d = document.createElement("div");
      d.className = "step " + (s.ok ? "ok" : "fail");
      d.textContent = (s.ok ? "✓ " : "✗ ") + s.name + " — " + (s.detail || "");
      box.appendChild(d);
    });
    if (r.recordId) {
      var t = document.createElement("div");
      t.className = "step ok";
      t.textContent = "→ recordId = " + r.recordId;
      box.appendChild(t);
    }
  }

  function post(url, body, cb) {
    fetch(url, { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body) })
      .then(function (x) { return x.json(); })
      .then(cb)
      .catch(function (e) { alert("请求失败: " + e); });
  }

  document.getElementById("btnSample").onclick = sampleTrack;
  document.getElementById("btnClear").onclick = function () {
    pts = []; redraw();
  };
  document.getElementById("btnGen").onclick = function () {
    if (pts.length < 2) { alert("请先在地图上点至少 2 个点，或点「生成示例跑道」"); return; }
    post("/api/generate", { params: params() }, function (g) {
      if (!g.ok) { alert("生成失败: " + g.msg); return; }
      showMetrics(g);
    });
  };
  document.getElementById("btnSubmit").onclick = function () {
    if (pts.length < 2) { alert("请先生成轨迹"); return; }
    post("/api/submit", { params: params(),
      faces: document.getElementById("faces").value === "1",
      run_type: parseInt(document.getElementById("runType").value, 10) },
      function (r) { showSteps(r); });
  };

  sampleTrack(); // 默认给一条示例跑道
})();
