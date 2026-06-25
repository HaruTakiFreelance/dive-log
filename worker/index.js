/**
 * Cloudflare Worker — Notion API Proxy for Dive Log
 *
 * Secrets (set via: wrangler secret put NOTION_TOKEN):
 *   NOTION_TOKEN
 *
 * Vars (wrangler.toml):
 *   DIVE_LOG_DB, FISH_DB
 */

const ALLOWED_ORIGIN = 'https://harutakifreelance.github.io';

const CORS = {
  'Access-Control-Allow-Origin': ALLOWED_ORIGIN,
  'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
  'Access-Control-Allow-Headers': 'Content-Type',
};

function respond(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { ...CORS, 'Content-Type': 'application/json' },
  });
}

async function notion(env, method, path, body = null) {
  const res = await fetch(`https://api.notion.com/v1${path}`, {
    method,
    headers: {
      Authorization: `Bearer ${env.NOTION_TOKEN}`,
      'Notion-Version': '2022-06-28',
      'Content-Type': 'application/json',
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    const err = await res.text();
    throw new Error(`Notion ${res.status}: ${err}`);
  }
  return res.json();
}

export default {
  async fetch(request, env) {
    if (request.method === 'OPTIONS') {
      return new Response(null, { headers: CORS });
    }

    const { pathname, searchParams } = new URL(request.url);

    try {
      // ── 最終ダイブ情報取得（入力デフォルト用）──
      if (pathname === '/dive/last' && request.method === 'GET') {
        const data = await notion(env, 'POST', `/databases/${env.DIVE_LOG_DB}/query`, {
          sorts: [{ property: '日付', direction: 'descending' }],
          page_size: 1,
        });
        if (!data.results?.length) return respond({});
        const p = data.results[0].properties;
        return respond({
          dive_number: (p['何本目か']?.number ?? 0) + 1,
          weight:      p['ウェイト']?.number ?? null,
          location:    p['場所']?.rich_text?.[0]?.plain_text ?? '',
        });
      }

      // ── 魚検索 ──
      if (pathname === '/fish/search' && request.method === 'GET') {
        const q = searchParams.get('q') || '';
        const data = await notion(env, 'POST', `/databases/${env.FISH_DB}/query`, {
          filter: { property: '名前', title: { contains: q } },
          page_size: 20,
        });
        const results = (data.results || [])
          .filter(p => p.properties['名前']?.title?.length)
          .map(p => ({
            id:   p.id,
            name: p.properties['名前'].title[0].plain_text,
          }));
        return respond(results);
      }

      // ── 魚情報AI自動入力 ──
      if (pathname === '/fish/suggest' && request.method === 'POST') {
        const { name } = await request.json();
        const aiRes = await fetch('https://api.anthropic.com/v1/messages', {
          method: 'POST',
          headers: {
            'x-api-key': env.ANTHROPIC_API_KEY,
            'anthropic-version': '2023-06-01',
            'content-type': 'application/json',
          },
          body: JSON.stringify({
            model: 'claude-haiku-4-5-20251001',
            max_tokens: 400,
            messages: [{
              role: 'user',
              content: `海の生き物「${name}」の情報をJSONで返してください。
english_name: 英名（なければ空文字）
scientific_name: 学名（なければ空文字）
category: 分類（魚類/甲殻類/頭足類/棘皮動物/軟体動物/その他 のどれか）
memo: 生息域・特徴など1〜2文（日本語）
JSONのみ返してください。`
            }]
          })
        });
        const aiData = await aiRes.json();
        const text = aiData.content?.[0]?.text || '{}';
        const match = text.match(/\{[\s\S]*\}/);
        try {
          return respond(match ? JSON.parse(match[0]) : {});
        } catch {
          return respond({});
        }
      }

      // ── 魚追加 ──
      if (pathname === '/fish/add' && request.method === 'POST') {
        const d = await request.json();
        const props = {
          '名前': { title: [{ text: { content: d.name } }] },
        };
        if (d.english_name)    props['英名']  = { rich_text: [{ text: { content: d.english_name } }] };
        if (d.scientific_name) props['学名']  = { rich_text: [{ text: { content: d.scientific_name } }] };
        if (d.category)        props['分類']  = { select: { name: d.category } };
        if (d.memo)            props['メモ']  = { rich_text: [{ text: { content: d.memo } }] };
        if (d.rarity)          props['レア度'] = { rich_text: [{ text: { content: d.rarity } }] };

        const page = await notion(env, 'POST', '/pages', {
          parent: { database_id: env.FISH_DB },
          properties: props,
        });
        return respond({ id: page.id, name: d.name });
      }

      // ── ダイブ記録追加 ──
      if (pathname === '/dive/add' && request.method === 'POST') {
        const d = await request.json();
        const autoName = `${d.date} ${d.point || d.location} #${d.dive_number}`;
        const props = {
          '名前':      { title:     [{ text: { content: autoName } }] },
          '日付':      { date:      { start: d.date } },
          '何本目か':  { number:    d.dive_number },
          '場所':      { rich_text: [{ text: { content: d.location } }] },
          'ポイント':  { rich_text: [{ text: { content: d.point || '' } }] },
          '開始時刻':  { rich_text: [{ text: { content: d.start_time || '' } }] },
          '終了時刻':  { rich_text: [{ text: { content: d.end_time || '' } }] },
          '潜水時間':  { number:    d.duration },
          'Max Depth': { number:    d.max_depth },
          'ウェイト':  { number:    d.weight },
        };
        if (d.comment)           props['コメント']      = { rich_text: [{ text: { content: d.comment } }] };
        if (d.cost)              props['かかった金額']   = { number: d.cost };
        if (d.video_links)       props['動画リンク']     = { rich_text: [{ text: { content: d.video_links } }] };
        if (d.fish_ids?.length)  props['見れた魚']       = { relation: d.fish_ids.map(id => ({ id })) };

        await notion(env, 'POST', '/pages', {
          parent: { database_id: env.DIVE_LOG_DB },
          properties: props,
        });
        return respond({ ok: true });
      }

      return respond({ error: 'Not found' }, 404);

    } catch (e) {
      return respond({ error: e.message }, 500);
    }
  },
};
