console.log("[CIC] SYSTEM BOOT: JS Loading");

(function() {
    console.log("[CIC] Init Sequence Started");
    var btnAcquire = document.getElementById('btnAcquire');
    var targetUrl = document.getElementById('targetUrl');
    var statusMsg = document.getElementById('acquisitionStatus');
    var coaPanel = document.getElementById('coaPanel');
    var coaContainer = document.getElementById('coaContainer');
    var currentMissionId = null;

    if(!btnAcquire) return;

    btnAcquire.addEventListener('click', function() {
        console.log("[CIC] ACQUIRE btn clicked. URL: ", targetUrl.value);
        if(!targetUrl.value) {
            statusMsg.textContent = "⚠️ URLを入力してください。";
            return;
        }
        statusMsg.textContent = ">>> SCANNING TARGET...";
        btnAcquire.disabled = true;

        fetch('/api/cic/webhook/share', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url: targetUrl.value })
        })
        .then(function(res) {
            if(!res.ok) {
                if(res.status === 429) {
                    return res.json().then(function(data) {
                        showToast(data.detail);
                        statusMsg.textContent = "[RESTRICTED] " + data.detail;
                        throw new Error("429");
                    });
                }
                throw new Error("HTTP error " + res.status);
            }
            return res.json();
        })
        .then(function(data) {
            console.log("[CIC] Data acquired:", data);
            currentMissionId = data.mission_id;
            statusMsg.textContent = ">>> TARGET ACQUIRED. MISSION ID: " + currentMissionId;
            coaPanel.style.opacity = "1";
            coaPanel.style.pointerEvents = "auto";
            renderCOAs(data.coas);
            btnAcquire.disabled = false;
        })
        .catch(function(e) {
            console.error("[CIC] API Error:", e);
            if(e.message !== "429") {
                statusMsg.textContent = "SYSTEM ERROR: " + e.message;
            }
            btnAcquire.disabled = false;
        });
    });

    function renderCOAs(coas) {
        coaContainer.innerHTML = '';
        for(var i=0; i<coas.length; i++) {
            (function(coa) {
                var div = document.createElement('div');
                div.className = 'coa-card';
                
                var h3 = document.createElement('h3');
                h3.textContent = coa.coa_type;
                div.appendChild(h3);
                
                var intentP = document.createElement('p');
                var intentLabel = document.createElement('strong');
                intentLabel.textContent = 'INTENT:';
                intentP.appendChild(intentLabel);
                intentP.appendChild(document.createTextNode(' ' + coa.tactical_intent));
                div.appendChild(intentP);
                
                var textP = document.createElement('p');
                var textLabel = document.createElement('strong');
                textLabel.textContent = 'TEXT:';
                textP.appendChild(textLabel);
                textP.appendChild(document.createTextNode(' '));
                var warheadSpan = document.createElement('span');
                warheadSpan.className = 'warhead-text';
                warheadSpan.textContent = coa.nazokake_text;
                textP.appendChild(warheadSpan);
                div.appendChild(textP);
                
                var btn = document.createElement('button');
                btn.textContent = 'SELECT & FIRE';
                btn.addEventListener('click', function() { auditAndFire(coa.nazokake_text); });
                div.appendChild(btn);
                
                coaContainer.appendChild(div);
            })(coas[i]);
        }
    }

    function auditAndFire(text) {
        if(!currentMissionId) return;
        console.log("[CIC] Firing sequence started.");
        
        fetch('/api/cic/missions/' + currentMissionId + '/audit', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ selected_warhead: text })
        })
        .then(function(res) { return res.json(); })
        .then(function(auditData) {
            showToast("G-7 AUDIT: " + auditData.warning_message);
            setTimeout(function() {
                fetch('/api/cic/missions/' + currentMissionId + '/fire', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ selected_warhead: text })
                })
                .then(function(res) { return res.json(); })
                .then(function(fireData) {
                    showToast(fireData.message);
                    coaContainer.innerHTML = '<p class="placeholder-text">WARHEAD FIRED. BDA ACTIVATED.</p>';
                    coaPanel.style.opacity = "0.5";
                    coaPanel.style.pointerEvents = "none";
                });
            }, 3000);
        })
        .catch(function(e) {
            showToast("FIRE SEQUENCE ERROR");
        });
    }

    function showToast(msg) {
        var t = document.createElement('div');
        t.className = 'toast';
        t.textContent = msg;
        document.getElementById('toastContainer').appendChild(t);
        setTimeout(function() {
            if(t.parentNode) { t.parentNode.removeChild(t); }
        }, 6000);
    }
})();
