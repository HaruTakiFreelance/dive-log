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

      // ── 魚情報取得（shiny-ace.com スクレイプ、ai.py と同じロジック）──
      if (pathname === '/fish/suggest' && request.method === 'POST') {
        const { name } = await request.json();
        const UA = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36';

        // 1. インデックスページから魚のURLを探す
        const idxRes = await fetch('https://shiny-ace.com/sakuin.html', { headers: { 'User-Agent': UA } });
        const idxHtml = await idxRes.text();
        const idxLinks = [...idxHtml.matchAll(/href="(zukan\/[^"]+)"[^>]*>([^<]+)</g)];
        let fishUrl = null;
        for (const [, href, linkName] of idxLinks) {
          const ln = linkName.trim();
          if (ln === name || ln.includes(name) || name.includes(ln)) {
            fishUrl = 'https://shiny-ace.com/' + href;
            break;
          }
        }
        if (!fishUrl) return respond({});

        // 2. 魚ページを取得してテキスト化
        const pageRes = await fetch(fishUrl, { headers: { 'User-Agent': UA } });
        const pageHtml = await pageRes.text();
        const text = pageHtml
          .replace(/<script[\s\S]*?<\/script>/gi, '')
          .replace(/<style[\s\S]*?<\/style>/gi, '')
          .replace(/<[^>]+>/g, '\n')
          .replace(/&nbsp;/g, ' ')
          .replace(/&#[0-9]+;/g, '')
          .replace(/&[a-z]+;/g, '');

        // 3. フィールド抽出（ai.py と同じパターン）
        const findField = (label) => {
          const m = text.match(new RegExp(label + '[\\uff1a:\\s　]*([^\\n]+)'));
          return m ? m[1].trim() : '';
        };
        const findStars = (label) => {
          const m = text.match(new RegExp(label + '[\\uff1a:\\s　]*([★☆\\n]+)'));
          return m ? m[1].replace(/\n/g, '').trim() : '';
        };

        const english_name    = findField('英名');
        const sciM            = text.match(/\n([A-Z][a-z]+ [a-z][a-z]+(?:\s+[a-z]+)?)\n/);
        const scientific_name = sciM ? sciM[1].trim() : '';
        const habitat         = findField('生息');
        const distribution    = findField('分布');
        const rarity          = findStars('レア度');
        const popularity      = findStars('人気');
        const photo_ease      = findStars('撮り易さ');
        const orderM          = text.match(/-\s*(.+目)\s*-/);
        const familyM         = text.match(/\n([^\n]+科)\n/);
        const genusM          = text.match(/-\s*(.+属)/);
        const order           = orderM  ? orderM[1].trim()  : '';
        const family          = familyM ? familyM[1].trim() : '';
        const genus           = genusM  ? genusM[1].trim()  : '';

        // 4. カテゴリ判定（ai.py と同じ）
        const CATEGORY_KEYWORDS = [
          ['軟体動物', ['軟体動物','頭足綱','腹足綱','二枚貝綱','タコ目','イカ目']],
          ['甲殻類',   ['甲殻類','十脚目','口脚目','フジツボ']],
          ['棘皮動物', ['棘皮動物','ヒトデ綱','ウニ綱','ナマコ綱']],
          ['爬虫類',   ['爬虫類','ウミガメ科','カメ目']],
          ['哺乳類',   ['哺乳類','クジラ目','鯨偶蹄目']],
        ];
        let category = '魚類';
        for (const [cat, keywords] of CATEGORY_KEYWORDS) {
          if (keywords.some(kw => text.includes(kw))) { category = cat; break; }
        }

        const memoParts = [habitat, distribution ? `分布：${distribution}` : ''].filter(Boolean);
        return respond({ english_name, scientific_name, category, order, family, genus,
                         memo: memoParts.join('　'), rarity, popularity, photo_ease });
      }

      // ── 魚追加 ──
      if (pathname === '/fish/add' && request.method === 'POST') {
        const d = await request.json();
        const props = {
          '名前': { title: [{ text: { content: d.name } }] },
        };
        if (d.english_name)    props['英名']      = { rich_text: [{ text: { content: d.english_name } }] };
        if (d.scientific_name) props['学名']      = { rich_text: [{ text: { content: d.scientific_name } }] };
        if (d.category)        props['分類']      = { select: { name: d.category } };
        if (d.memo)            props['メモ']      = { rich_text: [{ text: { content: d.memo } }] };
        if (d.order)           props['目']        = { rich_text: [{ text: { content: d.order } }] };
        if (d.family)          props['科']        = { rich_text: [{ text: { content: d.family } }] };
        if (d.genus)           props['属']        = { rich_text: [{ text: { content: d.genus } }] };
        if (d.rarity)          props['レア度']    = { rich_text: [{ text: { content: d.rarity } }] };
        if (d.popularity)      props['人気']      = { rich_text: [{ text: { content: d.popularity } }] };
        if (d.photo_ease)      props['撮りやすさ'] = { rich_text: [{ text: { content: d.photo_ease } }] };

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
