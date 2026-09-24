// HRMOS エージェント画面から、招待されている全企業の求人（本文つき）を JSON で書き出す。
// 使い方: https://hrmos.co/agent/ にログインした状態で、このファイルの中身を DevTools のコンソールに貼って実行する
//         （またはブックマークレットとして登録してクリック）。~/Downloads に hrmos_export_YYYYMMDD.json が保存される。
// 認証はブラウザのログイン状態をそのまま使い、トークンやクッキーは読み出さない。
(async () => {
  const get = async (path) => (await fetch(path, { credentials: 'include' })).json();
  const text = (c) => {
    if (!c) return '';
    const parts = [c.jobAdTitle || ''];
    if (c.salary) parts.push(`給与: ${c.salary.amountFrom ?? ''}〜${c.salary.amountTo ?? ''} ${c.salary.supplement || ''}`);
    if (c.locations) parts.push('勤務地: ' + c.locations.map((l) => l.address).join(' / '));
    for (const d of c.descriptions || []) parts.push(`■${d.term}\n${d.description}`);
    if (c.markdownFreeText) parts.push(c.markdownFreeText);
    return parts.filter(Boolean).join('\n\n');
  };
  const out = { source: 'HRMOS', exportedAt: new Date().toISOString(), corporates: [] };
  for (const corp of await get('/api/other/agent/corporates')) {
    const jobs = await get(`/api/other/agent/corporates/${corp.id}/jobs`);
    out.corporates.push({
      name: corp.name,
      jobs: jobs.map((j) => ({
        jobId: j.jobId,
        title: j.jobName || j.jobAdTitle,
        accessLevel: j.status?.accessLevel,
        archived: !!j.status?.isArchived,
        closeAt: j.status?.closeAt || j.closeAt || null,
        text: text(j.content),
      })),
    });
  }
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([JSON.stringify(out)], { type: 'application/json' }));
  a.download = `hrmos_export_${out.exportedAt.slice(0, 10).replaceAll('-', '')}.json`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  return `${out.corporates.length}社 / ${out.corporates.reduce((s, c) => s + c.jobs.length, 0)}件を書き出しました`;
})();
