async function loadComponent(id, file) {
  try {
    const res = await fetch(file);
    if (!res.ok) {
      throw new Error(`Failed to load ${file}: ${res.status}`);
    }
    const html = await res.text();
    document.getElementById(id).innerHTML = html;
  } catch (error) {
    console.error("Error loading component:", error);
  }
}
