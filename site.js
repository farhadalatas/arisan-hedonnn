(() => {
  const page = document.body.dataset.page || "";
  let csrfToken = "";

  const navToggle = document.getElementById("navToggle");
  const siteNav = document.getElementById("siteNav");
  if (navToggle && siteNav) navToggle.addEventListener("click", () => {
    const open = siteNav.classList.toggle("show");
    navToggle.setAttribute("aria-expanded", String(open));
  });

  async function api(path, options = {}) {
    const method = String(options.method || "GET").toUpperCase();
    const headers = { ...(options.headers || {}) };
    if (method !== "GET") {
      headers["Content-Type"] = "application/json";
      if (csrfToken) headers["X-CSRF-Token"] = csrfToken;
    }
    const response = await fetch(path, { cache:"no-store", credentials:"same-origin", ...options, headers });
    const payload = await response.json().catch(() => ({ ok:false, error:"Respons server tidak valid." }));
    if (!response.ok) {
      const error = new Error(payload.error || "Request gagal.");
      error.status = response.status;
      throw error;
    }
    if (payload.csrfToken) csrfToken = payload.csrfToken;
    return payload;
  }

  function setFeedback(element, message, success = false) {
    if (!element) return;
    element.textContent = message || "";
    element.classList.toggle("success", success);
  }

  function safeNext(fallback) {
    const value = new URLSearchParams(location.search).get("next") || fallback;
    return value.startsWith("/") && !value.startsWith("//") ? value : fallback;
  }

  async function redirectIfLoggedIn() {
    try {
      const status = await api("/api/account/status");
      if (status.authenticated) location.replace(safeNext("/dashboard"));
    } catch (_) {}
  }

  if (page === "login") {
    redirectIfLoggedIn();
    const form = document.getElementById("loginForm");
    const feedback = document.getElementById("formFeedback");
    form.addEventListener("submit", async event => {
      event.preventDefault();
      const button = form.querySelector("button[type=submit]");
      button.disabled = true; button.textContent = "Memeriksa..."; setFeedback(feedback, "");
      try {
        await api("/api/account/login", { method:"POST", body:JSON.stringify({ email:form.email.value, password:form.password.value }) });
        setFeedback(feedback, "Login berhasil. Membuka dashboard...", true);
        location.replace(safeNext("/dashboard"));
      } catch (error) {
        setFeedback(feedback, error.message);
      } finally {
        button.disabled = false; button.textContent = "Masuk";
      }
    });
  }

  if (page === "register") {
    redirectIfLoggedIn();
    const form = document.getElementById("registerForm");
    const feedback = document.getElementById("formFeedback");
    form.addEventListener("submit", async event => {
      event.preventDefault();
      if (!form.reportValidity()) return;
      if (form.password.value !== form.confirm.value) { setFeedback(feedback, "Ulangi password harus sama."); return; }
      const button = form.querySelector("button[type=submit]");
      button.disabled = true; button.textContent = "Membuat workspace..."; setFeedback(feedback, "");
      try {
        await api("/api/account/register", { method:"POST", body:JSON.stringify({ name:form.name.value, workspace:form.workspace.value, email:form.email.value, password:form.password.value }) });
        setFeedback(feedback, "Akun berhasil dibuat. Membuka dashboard...", true);
        location.replace("/dashboard");
      } catch (error) {
        setFeedback(feedback, error.message);
      } finally {
        button.disabled = false; button.textContent = "Buat akun & workspace";
      }
    });
  }

  function eventCard(item) {
    const article = document.createElement("article"); article.className = "event-card";
    const top = document.createElement("div"); top.className = "event-card-top";
    const heading = document.createElement("h3"); heading.textContent = item.name;
    const status = document.createElement("span"); status.className = "event-status"; status.textContent = item.status === "draft" ? "Siap" : item.status;
    top.append(heading, status);
    const numbers = document.createElement("div"); numbers.className = "event-numbers";
    [[item.participants,"Peserta"],[item.winners,"Pemenang"]].forEach(([value,label]) => { const box=document.createElement("div"); const strong=document.createElement("strong"); const span=document.createElement("span"); strong.textContent=value; span.textContent=label; box.append(strong,span); numbers.appendChild(box); });
    const link = document.createElement("a"); link.className = "button button-ghost"; link.href = `/app?event=${encodeURIComponent(item.id)}`; link.textContent = "Buka panggung";
    article.append(top, numbers, link); return article;
  }

  async function loadDashboard() {
    try {
      const data = await api("/api/dashboard");
      document.getElementById("accountName").textContent = data.user.name;
      document.getElementById("accountEmail").textContent = data.user.email;
      document.getElementById("workspaceGreeting").textContent = `${data.workspace.name}, siap bikin acara?`;
      document.getElementById("workspaceMeta").textContent = `Role ${data.workspace.role} - database lokal aktif`;
      document.getElementById("totalEvents").textContent = data.events.length;
      document.getElementById("totalParticipants").textContent = data.events.reduce((sum,item)=>sum+item.participants,0);
      document.getElementById("totalWinners").textContent = data.events.reduce((sum,item)=>sum+item.winners,0);
      const grid = document.getElementById("eventGrid"); grid.innerHTML = "";
      if (!data.events.length) { const empty=document.createElement("div"); empty.className="empty-events"; empty.textContent="Belum ada acara. Buat acara pertama lo."; grid.appendChild(empty); }
      else data.events.forEach(item => grid.appendChild(eventCard(item)));
    } catch (error) {
      if (error.status === 401) location.replace("/login?next=/dashboard");
      else document.getElementById("eventGrid").textContent = error.message;
    }
  }

  if (page === "dashboard") {
    loadDashboard();
    const dialog = document.getElementById("eventDialog");
    const form = document.getElementById("eventForm");
    const feedback = document.getElementById("eventFeedback");
    document.getElementById("openCreateEvent").addEventListener("click", () => { dialog.hidden=false; document.getElementById("eventName").focus(); });
    document.getElementById("cancelEvent").addEventListener("click", () => { dialog.hidden=true; form.reset(); setFeedback(feedback,""); });
    dialog.addEventListener("click", event => { if(event.target===dialog) document.getElementById("cancelEvent").click(); });
    form.addEventListener("submit", async event => {
      event.preventDefault(); const button=form.querySelector("button[type=submit]"); button.disabled=true; setFeedback(feedback,"");
      try { const result=await api("/api/events",{method:"POST",body:JSON.stringify({name:document.getElementById("eventName").value})}); location.href=result.next; }
      catch(error){setFeedback(feedback,error.message); button.disabled=false;}
    });
    document.getElementById("logoutBtn").addEventListener("click", async () => {
      try { await api("/api/account/logout",{method:"POST",body:"{}"}); } catch (_) {}
      location.replace("/");
    });
  }
})();
