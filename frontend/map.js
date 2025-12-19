// ===== Utility helpers =====
const flagFromCC = (cc) => {
  if (!cc || cc.length !== 2) return "🇺🇳";
  const base = 0x1F1E6 - "A".charCodeAt(0);
  return String.fromCodePoint(...cc.toUpperCase().split("").map(c => base + c.charCodeAt(0)));
};
const haversineKm = (a, b) => {
  if (!a || !b) return 0;
  const [lat1, lon1] = a, [lat2, lon2] = b;
  if (lat1==null||lon1==null||lat2==null||lon2==null) return 0;
  const R=6371, d2r=Math.PI/180;
  const dLat=(lat2-lat1)*d2r, dLon=(lon2-lon1)*d2r;
  const x=Math.sin(dLat/2)**2 + Math.cos(lat1*d2r)*Math.cos(lat2*d2r)*Math.sin(dLon/2)**2;
  return 2*R*Math.asin(Math.sqrt(x));
};
const classifyRole = (hop, idx) => {
  if (!hop || !hop.ip) return "Timeout / Filtered";
  if (hop.city === "Private Network") return "Local Gateway";
  const org = (hop.org||"").toLowerCase();
  const asn = (hop.asn_name||"").toLowerCase();
  if (org.includes("google") || asn.includes("google") || (hop.asn && `${hop.asn}`.includes("15169")))
    return "Destination Network Edge";
  if (idx === 1) return "ISP Entry Point";
  return "Transit Node";
};
const CONTINENT = {
  US:"NA",CA:"NA",MX:"NA",PR:"NA",
  GB:"EU",IE:"EU",FR:"EU",DE:"EU",NL:"EU",ES:"EU",IT:"EU",SE:"EU",NO:"EU",DK:"EU",PL:"EU",
  BR:"SA",AR:"SA",CL:"SA",CO:"SA",PE:"SA",
  JP:"AS",CN:"AS",KR:"AS",SG:"AS",HK:"AS",TW:"AS",IN:"AS",AE:"AS",SA:"AS",TR:"AS",IL:"AS",
  AU:"OC",NZ:"OC",
  ZA:"AF",NG:"AF",EG:"AF",MA:"AF",KE:"AF",
};
const bezierPoints = (a, b, sameContinent) => {
  const p0 = [a.lat, a.lon], p2 = [b.lat, b.lon];
  const dist = haversineKm(p0, p2);
  if (!sameContinent || dist > 3000) return [p0, p2];
  const dx = p2[1]-p0[1], dy = p2[0]-p0[0];
  const len = Math.sqrt(dx*dx+dy*dy) || 1;
  const perp = [-dy/len, dx/len];
  const offsetDeg = Math.min(3, (dist*0.15)/111); // damp curvature; stays modest
  const mid = [(p0[0]+p2[0])/2, (p0[1]+p2[1])/2];
  const ctrl = [mid[0] + perp[0]*offsetDeg, mid[1] + perp[1]*offsetDeg];
  const pts = [];
  for (let t=0;t<=1.0001;t+=0.05) {
    const u = 1-t;
    const lat = u*u*p0[0] + 2*u*t*ctrl[0] + t*t*p2[0];
    const lon = u*u*p0[1] + 2*u*t*ctrl[1] + t*t*p2[1];
    pts.push([lat, lon]);
  }
  return pts;
};
const smoothPathCoords = (pts) => {
  if (!pts || pts.length < 2) return pts || [];
  const out = [];
  for (let i=0;i<pts.length-1;i++){
    const a = pts[i], b = pts[i+1];
    const dist = haversineKm(a, b);
    // big jumps stay straight
    if (dist > 5000){
      if (!out.length) out.push(a);
      out.push(b);
      continue;
    }
    // mild curvature
    const dx = b[1]-a[1], dy = b[0]-a[0];
    const len = Math.sqrt(dx*dx+dy*dy) || 1;
    const perp = [-dy/len, dx/len];
    const offsetDeg = Math.min(2.5, (dist*0.12)/111);
    const mid = [(a[0]+b[0])/2, (a[1]+b[1])/2];
    const ctrl = [mid[0] + perp[0]*offsetDeg, mid[1] + perp[1]*offsetDeg];
    for (let t=0;t<=1.0001;t+=0.08){
      const u=1-t;
      const lat = u*u*a[0] + 2*u*t*ctrl[0] + t*t*b[0];
      const lon = u*u*a[1] + 2*u*t*ctrl[1] + t*t*b[1];
      if (!out.length || haversineKm(out[out.length-1],[lat,lon])>0.5){
        out.push([lat,lon]);
      }
    }
  }
  return out;
};

document.addEventListener('DOMContentLoaded', () => {
  // Map
  const map = L.map('map').setView([20,0], 2);
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{
    maxZoom: 18, attribution:'© OpenStreetMap contributors'
  }).addTo(map);

  const layers = {
    tcp:  { markers: L.layerGroup().addTo(map), lines: L.layerGroup().addTo(map), latlngs: [], hops: [], undersea: L.layerGroup().addTo(map) },
    icmp: { markers: L.layerGroup().addTo(map), lines: L.layerGroup().addTo(map), latlngs: [], hops: [], undersea: L.layerGroup().addTo(map) },
    udp:  { markers: L.layerGroup().addTo(map), lines: L.layerGroup().addTo(map), latlngs: [], hops: [], undersea: L.layerGroup().addTo(map) },
  };

  // UI elements
  const form = document.getElementById('traceForm');
  const hopList = document.getElementById('hopList');
  const results = document.getElementById('results');
  const statHops = document.getElementById('statHops');
  const statCountries = document.getElementById('statCountries');
  const statAsnCount = document.getElementById('statAsnCount');
  const statDistance = document.getElementById('statDistance');
  const asnPathEl = document.getElementById('asnPath');
  const stopBtn = document.getElementById('stopBtn');
  const shareBtn = document.getElementById('shareBtn');
  const exportJsonBtn = document.getElementById('exportJsonBtn');
  const exportCsvBtn = document.getElementById('exportCsvBtn');

  // RTT chart
  const rttCtx = document.getElementById('rttChart').getContext('2d');
  const css = getComputedStyle(document.documentElement);
  const rttChart = new Chart(rttCtx, {
    type: 'line',
    data: { labels: [], datasets: [
      { label:'TCP',  data:[], borderColor:css.getPropertyValue('--tcp').trim(),  tension:0.2 },
      { label:'ICMP', data:[], borderColor:css.getPropertyValue('--icmp').trim(), tension:0.2 },
      { label:'UDP',  data:[], borderColor:css.getPropertyValue('--udp').trim(),  tension:0.2 },
    ]},
    options: { animation:false, responsive:true, scales:{ y:{ beginAtZero:true, title:{display:true,text:'ms'}}, x:{ title:{display:true,text:'Hop'}} } }
  });

  // State per run
  let eventSources = {};
  let allHops = { tcp:[], icmp:[], udp:[] };
  let countrySet = new Set();
  let asnOrder = [];
  let totalDistanceKm = 0;

  const closeEventSources = () => {
    Object.values(eventSources).forEach(es => es.close());
    eventSources = {};
  };

  const resetState = () => {
    closeEventSources();
    Object.values(layers).forEach(({markers,lines,undersea}) => { markers.clearLayers(); lines.clearLayers(); undersea.clearLayers(); });
    layers.tcp.latlngs = []; layers.icmp.latlngs = []; layers.udp.latlngs = [];
    layers.tcp.hops = []; layers.icmp.hops = []; layers.udp.hops = [];
    hopList.innerHTML = ''; results.textContent = 'Tracing...';
    allHops = { tcp:[], icmp:[], udp:[] };
    countrySet = new Set(); asnOrder = []; totalDistanceKm = 0;
    statHops.textContent = '0'; statCountries.textContent = '0'; statAsnCount.textContent = '0'; statDistance.textContent = '0 km';
    asnPathEl.textContent = '–';
    rttChart.data.labels = []; rttChart.data.datasets.forEach(ds => ds.data = []); rttChart.update();
  };

  // UI add
  const addHopToUI = (proto, hop, idx) => {
    if (hop.timeout_count) {
      const li = document.createElement('li');
      li.className = 'hop-item timeout'; li.dataset.proto = proto; li.dataset.index = String(idx);
      li.innerHTML = `
        <div class="hop-head"><span class="flag">🇺🇳</span><strong>Request timed out x${hop.timeout_count}</strong></div>
        <div class="meta">–</div><div class="role">Timeout / Filtered</div><div class="org">Unknown Org</div>`;
      hopList.appendChild(li); hopList.scrollTop = hopList.scrollHeight; return;
    }
    const flag = flagFromCC(hop.country_code || (hop.country_code2 || ''));
    const role = classifyRole(hop, idx);
    const ipDisp = hop.ip || 'Request timed out';
    const rttDisp = (typeof hop.rtt === 'number') ? `${hop.rtt} ms` : '–';
    const orgDisp = hop.org || hop.asn_name || hop.isp || 'Unknown Org';
    const asnDisp = hop.asn ? (typeof hop.asn === 'object' ? `AS${hop.asn.asn}` : `${hop.asn}`) : '';
    const li = document.createElement('li');
    li.className = 'hop-item'; li.dataset.proto = proto; li.dataset.index = String(idx);
    li.innerHTML = `
      <div class="hop-head"><span class="flag" title="${hop.country||''}">${flag}</span><strong>${ipDisp}</strong></div>
      <div class="meta">${hop.hostname || ''}</div>
      <div class="meta">RTT: ${rttDisp} • ${hop.city||'Unknown'}, ${hop.country||''}</div>
      <div class="meta">Medium: ${hop.medium_guess || 'Unknown'}</div>
      <div class="role">${role}</div>
      <div class="org">${orgDisp} ${asnDisp ? '• ' + asnDisp : ''}</div>`;
    hopList.appendChild(li); hopList.scrollTop = hopList.scrollHeight;
    document.querySelectorAll('.hop-item.active').forEach(el=>el.classList.remove('active')); li.classList.add('active');
  };

  // map draw
  const drawHopOnMap = (proto, hop) => {
    if (!(hop.lat != null && hop.lon != null)) return;
    const layer = layers[proto];
    const color = css.getPropertyValue(proto==='icmp' ? '--icmp' : proto==='udp' ? '--udp' : '--tcp').trim();
    const ll = [hop.lat, hop.lon];
    const marker = L.circleMarker(ll, { radius:6, color, fillColor:color, fillOpacity:0.9 }).addTo(layer.markers);
    const asnDisp = hop.asn ? (typeof hop.asn === 'object' ? `AS${hop.asn.asn}` : hop.asn) : '';
    marker.bindPopup(`
      <strong>${hop.ip || ''}</strong><br/>
      ${hop.hostname || ''}<br/>
      RTT: ${(typeof hop.rtt==='number')? hop.rtt + ' ms' : '–'}<br/>
      ${hop.city||'Unknown'}, ${hop.country||''}<br/>
      Medium: ${hop.medium_guess || 'Unknown'}<br/>
      ${(hop.org || hop.asn_name || hop.isp || 'Unknown Org')} ${asnDisp ? '• '+asnDisp : ''}
    `);

    if (!layer.latlngs.length) map.setView(ll, 5);
    if (layer.latlngs.length) {
      const prev = layer.latlngs[layer.latlngs.length-1];
      const prevHop = layer.hops[layer.hops.length-1];
      let segPoints = null;
      if (hop.synthetic_path && hop.synthetic_path.length > 1) {
        const raw = hop.synthetic_path.map(p => [p[0], p[1]]);
        segPoints = smoothPathCoords(raw);
      } else if (prevHop) {
        const sameContinent = prevHop && hop && CONTINENT[prevHop.country_code] && CONTINENT[hop.country_code] && CONTINENT[prevHop.country_code] === CONTINENT[hop.country_code];
        segPoints = bezierPoints(prevHop, hop, sameContinent);
      } else {
        segPoints = [prev, ll];
      }
      const seg = L.polyline(segPoints, { color, weight:2, opacity:0.75 }).addTo(layer.lines);
      seg.setStyle({opacity:0.0});
      let op=0.0; const t=setInterval(()=>{ op+=0.15; seg.setStyle({opacity:Math.min(op,0.75)}); if(op>=0.75) clearInterval(t); }, 16);
      totalDistanceKm += haversineKm(prev, ll);
      statDistance.textContent = `${totalDistanceKm.toFixed(1)} km`;
    }
    layer.latlngs.push(ll);
    layer.hops.push(hop);
  };

  const drawUnderseaSegments = (proto, segs) => {
    const layer = layers[proto];
    const color = "#555"; // dashed neutral
    segs.forEach(s => {
      const a = [s.from.lat, s.from.lon], b = [s.to.lat, s.to.lon];
      const pl = L.polyline([a,b], { color, weight:3, opacity:0.9, dashArray: '6,6' }).addTo(layer.undersea);
      pl.bindTooltip(`${s.label} • ~${s.km} km\n${s.from.cc} (${s.from.city||''}) → ${s.to.cc} (${s.to.city||''})`, {sticky:true});
    });
  };

  const updateStats = (proto, hop, idx) => {
    if (hop.timeout_count) return;
    allHops[proto].push(hop);
    statHops.textContent = (allHops.tcp.length + allHops.icmp.length + allHops.udp.length).toString();
    if (hop.country_code) countrySet.add(hop.country_code);
    statCountries.textContent = String(countrySet.size);

    let asnNum = null;
    if (hop.asn) {
      if (typeof hop.asn === 'object' && hop.asn.asn) asnNum = `AS${hop.asn.asn}`;
      else if (typeof hop.asn === 'string') asnNum = hop.asn.startsWith('AS')? hop.asn : `AS${hop.asn}`;
    }
    if (asnNum && asnOrder[asnOrder.length-1] !== asnNum) {
      asnOrder.push(asnNum);
      asnPathEl.textContent = asnOrder.join(' → ');
      statAsnCount.textContent = String(new Set(asnOrder).size);
    }

    const dsIndex = ({tcp:0, icmp:1, udp:2})[proto];
    const ds = rttChart.data.datasets[dsIndex];
    const nextHopNumber = ds.data.length + 1;
    if (rttChart.data.labels.length < nextHopNumber) rttChart.data.labels.push(String(nextHopNumber));
    ds.data.push(typeof hop.rtt === 'number' ? hop.rtt : null);
    rttChart.update();
  };

  const explainTrace = () => {
    if (!allHops.tcp.length && !allHops.icmp.length && !allHops.udp.length) return;
    const seq = (allHops.tcp.length? allHops.tcp : (allHops.icmp.length? allHops.icmp : allHops.udp));
    const firstPub = seq.find(h => h && h.ip && (h.city!=="Private Network"));
    const orgs = [...new Set(seq.map(h => (h?.org || h?.asn_name || h?.isp)).filter(Boolean))];
    const countries = [...new Set(seq.map(h => h?.country_code).filter(Boolean))];
    const el = document.getElementById('explain');
    el.innerHTML = `
      <p>Your traffic leaves the local network${firstPub? ` near <strong>${firstPub.city||'Unknown'}, ${firstPub.country||''}</strong>`:''}, traverses ${orgs.length} providers (${orgs.slice(0,4).join(', ')}${orgs.length>4?'…':''}), and enters the destination’s edge network (${orgs.find(o=>/google|cloudflare|amazon|microsoft|azure|fastly|akamai/i.test(o))||'provider'}). The visible path crosses ${countries.length} country code(s): ${countries.join(', ')}. Total plotted distance: <strong>${totalDistanceKm.toFixed(1)} km</strong>.</p>
    `;
  };

  // Start/Stop logic
  const startTrace = (target, protos) => {
    resetState();
    const chosen = protos.length ? protos : ['tcp'];

    chosen.forEach(proto => {
      const qs = new URLSearchParams({ url: target, protocol: proto });
      const es = new EventSource(`/trace-stream?${qs.toString()}`);
      eventSources[proto] = es;

      es.onmessage = (ev) => {
        const hop = JSON.parse(ev.data);
        const idx = allHops[proto].length + 1;
        addHopToUI(proto, hop, idx);
        if (!hop.timeout_count) drawHopOnMap(proto, hop);
        updateStats(proto, hop, idx);
      };

      // NEW: consume meta (AS-PATH + physical segments)
      es.addEventListener('meta', (ev) => {
        const meta = JSON.parse(ev.data);
        if (meta.as_path && meta.as_path.length) {
          // Render AS-PATH prominently
          asnPathEl.textContent = meta.as_path.join(' → ');
          statAsnCount.textContent = String(new Set(meta.as_path).size);
        }
        if (meta.physical_segments && meta.physical_segments.length) {
          drawUnderseaSegments(proto, meta.physical_segments);
        }
      });

      es.addEventListener('done', () => {
        results.textContent = 'Trace complete.';
        es.close(); delete eventSources[proto];
        if (Object.keys(eventSources).length===0) explainTrace();
      });
      es.onerror = () => {
        results.textContent = 'Trace ended or failed.';
        es.close(); delete eventSources[proto];
        if (Object.keys(eventSources).length===0) explainTrace();
      };
    });
  };

  form.addEventListener('submit', (e) => {
    e.preventDefault();
    const target = document.getElementById('site').value.trim();
    const protos = [...document.querySelectorAll('input[name="proto"]:checked')].map(x=>x.value);
    if (!target) return;
    const url = new URL(location.href);
    url.searchParams.set('url', target);
    url.searchParams.set('protocol', protos.join(','));
    history.replaceState(null, '', url.toString());
    startTrace(target, protos);
  });

  document.getElementById('stopBtn').addEventListener('click', () => {
    closeEventSources();
    results.textContent = 'Stopped.';
  });

  document.getElementById('shareBtn').addEventListener('click', async () => {
    try { await navigator.clipboard.writeText(location.href); results.textContent = 'Share link copied to clipboard.'; }
    catch { results.textContent = 'Copy failed – select URL bar to share.'; }
  });

  const download = (filename, text) => {
    const a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([text],{type:'text/plain'}));
    a.download = filename; a.click(); URL.revokeObjectURL(a.href);
  };
  document.getElementById('exportJsonBtn').addEventListener('click', () => {
    const out = { generatedAt: new Date().toISOString(), runs: allHops };
    download('nettrace.json', JSON.stringify(out, null, 2));
  });
  document.getElementById('exportCsvBtn').addEventListener('click', () => {
    const rows = [['proto','hop','ip','rtt_ms','city','country','cc','org','asn','hostname','lat','lon','medium_guess']];
    ['tcp','icmp','udp'].forEach(proto => {
      allHops[proto].forEach((h,i)=>{
        rows.push([
          proto, i+1,
          h.ip||'',
          (typeof h.rtt==='number')?h.rtt:'',
          h.city||'', h.country||'', h.country_code||'',
          h.org||h.asn_name||h.isp||'',
          (typeof h.asn==='object'&&h.asn?.asn)?`AS${h.asn.asn}`:(h.asn||''),
          h.hostname||'',
          (h.lat??''), (h.lon??''),
          h.medium_guess||''
        ]);
      });
    });
    const csv = rows.map(r=>r.map(v=>String(v).replace(/"/g,'""')).map(v=>`"${v}"`).join(',')).join('\n');
    download('nettrace.csv', csv);
  });

  // Auto-start from query string
  const params = new URLSearchParams(location.search);
  const autoUrl = params.get('url'); const protoParam = params.get('protocol');
  if (autoUrl) {
    document.getElementById('site').value = autoUrl;
    const protos = (protoParam? protoParam.split(',') : ['tcp']).filter(p=>['tcp','icmp','udp'].includes(p));
    protos.forEach(p => {
      const cb = document.querySelector(`input[name="proto"][value="${p}"]`); if (cb) cb.checked = true;
    });
    startTrace(autoUrl, protos);
  }
});
