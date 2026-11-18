"""Generate Meta draft angles, copy and three images using the bots' OpenAI key.

Run inside the backend environment. No database or advertising API writes.
python scripts/meta_brand_draft_probe.py https://www.reliabletech.co.zw/ --output-dir /tmp/reliabletech-meta
"""
import argparse
import base64
import html
import json
import os
from pathlib import Path
import sys
from datetime import datetime, timezone

from openai import OpenAI
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.marketing_skills_probe import page_text
from modules.openclaw.marketing_skill_library import campaign_prompt, marketing_system


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('url')
    parser.add_argument('--snapshot', type=Path)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    if not os.getenv('OPENAI_API_KEY'):
        parser.error('Run in the backend environment where OPENAI_API_KEY is configured')
    evidence = page_text(args.url, args.snapshot)
    if len(evidence) < 100:
        parser.error('No usable website text was returned; stopping without inventing a brand')
    args.output_dir.mkdir(parents=True, exist_ok=True)
    client = OpenAI(timeout=180, max_retries=1)
    model = os.getenv('MARKETING_TEST_MODEL') or os.getenv('AD_COPY_MODEL') or 'gpt-5.4-mini'
    image_model = os.getenv('AD_IMAGE_MODEL', 'gpt-image-2.5-flare')
    result = {'url': args.url, 'created_at': datetime.now(timezone.utc).isoformat(),
              'text_model': model, 'image_model': image_model,
              'source': 'snapshot' if args.snapshot else 'live URL', 'status': 'started'}
    def save():
        (args.output_dir/'result.json').write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding='utf-8')
    def ask(prompt):
        response = client.chat.completions.create(model=model,
            messages=[{'role':'user','content':prompt}], response_format={'type':'json_object'})
        return json.loads(response.choices[0].message.content or '{}')
    try:
        campaign = ask(campaign_prompt({'url':args.url, 'content':evidence[:24000]}))
        sets = campaign.get('ad_sets')
        if not isinstance(sets, list) or len(sets) != 3:
            raise ValueError('Expected three draft ad angles')
        for entry in sets:
            copies = entry.get('copy_variations')
            if not isinstance(copies,list) or len(copies) != 3:
                raise ValueError('Expected three copy variations per angle')
            for variant in copies:
                if not variant.get('primary_text') or not variant.get('headline'):
                    raise ValueError('Incomplete ad copy')
                if len(variant['headline']) > 40 or len(variant.get('description','')) > 30:
                    raise ValueError('Ad copy exceeds the requested character limit')
        result['campaign'] = campaign
        save()
        contract = ('Return JSON {"prompts":[{"index":0,"prompt":"..."}]}, one prompt '
                    'for each of the three ad sets, indices 0,1,2. These are concept mockups. '
                    'No product or logo reference images were supplied. Use typographic designs '
                    'or clearly illustrative scenes; do not fabricate an exact branded product '
                    'or logo. Use only factual text supported by the website. Match each first '
                    'copy variation. Square Meta feed composition.')
        directions = ask(marketing_system('image',contract)+'\nEVIDENCE:\n'+evidence[:24000]
                         +'\nCAMPAIGN JSON:\n'+json.dumps(campaign))
        prompts = directions.get('prompts',[])
        if len(prompts)!=3 or {p.get('index') for p in prompts}!={0,1,2}:
            raise ValueError('Image direction missing an angle')
        result['image_directions'] = prompts
        result['images'] = []
        save()
        for direction in sorted(prompts,key=lambda p:p['index']):
            image = client.images.generate(model=image_model, prompt=direction['prompt'], size='1024x1024', n=1)
            if not image.data or not image.data[0].b64_json:
                raise ValueError('Image API returned no base64 image')
            name=f"angle-{direction['index']+1}.png"
            (args.output_dir/name).write_bytes(base64.b64decode(image.data[0].b64_json))
            result['images'].append(name)
            save()
        cards=[]
        for i,entry in enumerate(sets):
            copies=''.join('<h3>'+html.escape(v['headline'])+'</h3><p>'+html.escape(v['primary_text'])+'</p>' for v in entry['copy_variations'])
            cards.append('<section><h2>'+html.escape(entry['name'])+'</h2><img width="400" src="angle-'+str(i+1)+'.png">'+copies+'</section>')
        (args.output_dir/'preview.html').write_text('<!doctype html><meta charset="utf-8"><title>Meta draft test</title><style>body{font:16px system-ui;margin:40px;max-width:1100px}section{margin-bottom:48px}p{max-width:700px;white-space:pre-wrap}</style><h1>Meta draft test</h1><p>Concepts for review. No ads published. Illustrations have no supplied product/logo references.</p>'+''.join(cards), encoding='utf-8')
        result['status']='complete'
        save()
        print('Saved three angles, nine copies and three image concepts to '+str(args.output_dir))
    except Exception as exc:
        result['status']='failed'
        result['error_type']=type(exc).__name__
        result['http_status']=getattr(exc,'status_code',None)
        save()
        print('Draft test failed; see result.json for the completed stages and error type.',file=sys.stderr)
        raise SystemExit(1)

if __name__=='__main__':
    main()
