"""Browser smoke check against local seed_demo data; does not change records."""
import argparse
from pathlib import Path
from playwright.sync_api import sync_playwright, expect


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--base-url', default='http://127.0.0.1:8000')
    parser.add_argument('--channel', default='chrome', help='Installed Chrome/Edge channel; use chromium with playwright install chromium')
    args = parser.parse_args()
    output = Path('artifacts/browser')
    output.mkdir(parents=True, exist_ok=True)
    errors = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, channel=None if args.channel == 'chromium' else args.channel)
        for role in ['head', 'teacher', 'student']:
            context = browser.new_context(viewport={'width': 1440, 'height': 1000}, locale='ru-RU')
            page = context.new_page()
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.on('response', lambda response: errors.append(f'HTTP {response.status}: {response.url}') if response.status >= 500 else None)
            response = page.goto(args.base_url + '/login/')
            assert response.status == 200
            if role == 'head':
                page.screenshot(path=str(output / 'login.png'), full_page=True)
            page.locator('#id_username').fill(role)
            page.locator('#id_password').fill('Practice2026!')
            page.locator('form.stack button[type=submit], form.stack button').click()
            expect(page).to_have_url(args.base_url + '/')
            expect(page.locator('main h1')).to_be_visible()
            page.screenshot(path=str(output / f'{role}-desktop.png'), full_page=True)
            if role == 'head':
                page.goto(args.base_url + '/groups/')
                page.locator('.group-card').first.click()
                master = page.locator('[data-select-all]')
                expect(master).to_be_visible()
                expect(page.locator('[data-bulk-submit]')).to_be_disabled()
                master.check()
                expect(page.locator('[data-bulk-submit]')).to_be_enabled()
                boxes = page.locator('input[name=students][form=bulk-allocation]')
                assert boxes.count() > 1
                for box in boxes.all():
                    expect(box).to_be_checked()
                boxes.first.uncheck()
                assert master.evaluate('(element) => element.indeterminate')
                page.screenshot(path=str(output / 'head-group.png'), full_page=True)
                page.goto(args.base_url + '/teachers/')
                expect(page.locator('main table tbody tr')).to_have_count(2)
                page.goto(args.base_url + '/bank/?q=матрицы')
                expect(page.locator('.matrix-formula').first).to_be_visible()
                expect(page.locator('.matrix-formula .katex-error')).to_have_count(0)
                page.locator('.task-item').first.screenshot(path=str(output / 'matrix-card.png'))
                page.set_viewport_size({'width': 390, 'height': 844})
                assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'), 'Matrix card overflows mobile viewport'
                page.locator('.task-item').first.screenshot(path=str(output / 'matrix-card-mobile.png'))
                page.set_viewport_size({'width': 1440, 'height': 1000})
                page.goto(args.base_url + '/bank/new/')
                math_text = r'''Вычислите \(x^2\) и $y_1$.
\[\int_0^1 \frac{1}{1+x^2}\,dx\]
$$\begin{pmatrix}
1 & 2 \\
3 & 4
\end{pmatrix}$$
<img src=x onerror=alert(1)>'''
                page.locator('#id_text').fill(math_text)
                preview = page.locator('[data-math-preview="id_text"]')
                expect(preview.locator('.katex')).to_have_count(4)
                expect(preview.locator('.katex-error')).to_have_count(0)
                expect(preview.locator('img')).to_have_count(0)
                expect(page.locator('#id_text')).to_have_value(math_text)
                exponential_text = "Решите задачу Коши y' + 13y = exp(x), y(0) = 14. Также exp(−2x²), exp(0)."
                page.locator('#id_text').fill(exponential_text)
                expect(preview.locator('.exponential-formula .katex')).to_have_count(3)
                expect(preview.locator('.katex-error')).to_have_count(0)
                assert preview.locator('.exponential-formula annotation').all_text_contents() == ['e^{x}', 'e^{-2x^2}', 'e^{0}']
                expect(page.locator('#id_text')).to_have_value(exponential_text)
                preview.screenshot(path=str(output / 'exponential-preview.png'))
                page.locator('#id_text').fill('myexp(x), exp(), exp(<img>), обычный текст')
                expect(preview.locator('.exponential-formula')).to_have_count(0)
                plain_matrix = 'Для матрицы A = [[20, 1, 0], [1, 20, 1], [0, 1, 20]] найдите определитель.'
                page.locator('#id_text').fill(plain_matrix)
                expect(preview.locator('.matrix-formula .katex')).to_have_count(1)
                expect(page.locator('#id_text')).to_have_value(plain_matrix)
                page.locator('#id_text').fill('Неверная: [[1, 2], [3]]; текст: [["<img>", 2]]')
                expect(preview.locator('.matrix-formula')).to_have_count(0)
                expect(preview).to_contain_text('[[1, 2], [3]]')
                page.locator('#id_text').fill(math_text)
                expect(preview.locator('.katex')).to_have_count(4)
                page.set_viewport_size({'width': 390, 'height': 844})
                assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'), 'Math preview overflows mobile viewport'
                page.screenshot(path=str(output / 'latex-preview-mobile.png'), full_page=True)
                page.locator('#id_text').fill(r'$$\frac{1}$$')
                expect(preview.locator('.katex-error')).to_have_count(1)
            elif role == 'teacher':
                page.goto(args.base_url + '/groups/')
                page.locator('.group-card').first.click()
                expect(page.locator('.readiness-note')).to_be_visible()
            else:
                expect(page.locator('nav a[href="/teachers/"]')).to_have_count(0)
                expect(page.locator('nav a[href="/bank/"]')).to_have_count(0)
                page.locator('a.button[href^="/students/"]').click()
                with page.expect_download() as download:
                    page.locator('a[href$="/document/assignment/"]').click()
                assert download.value.suggested_filename.endswith('.docx')
            for path in ['/', page.url.removeprefix(args.base_url)]:
                page.set_viewport_size({'width': 390, 'height': 844})
                page.goto(args.base_url + path)
                assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'), f'{role}: mobile horizontal overflow on {path}'
            page.screenshot(path=str(output / f'{role}-mobile.png'), full_page=True)
            context.close()
            print(f'{role}: desktop, mobile, navigation OK')
        browser.close()
    assert not errors, '\n'.join(errors)
    print(f'Browser check passed. Screenshots: {output.resolve()}')


if __name__ == '__main__':
    main()
