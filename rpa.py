import asyncio
import os
import base64
from datetime import datetime
from pathlib import Path
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout

DOWNLOAD_DIR = Path("/app/downloads")
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)


async def run_rpa(email: str, password: str) -> dict:
    today = datetime.now().strftime("%d/%m/%Y")
    downloaded_files = []
    errors = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
            ]
        )
        context = await browser.new_context(
            accept_downloads=True,
            viewport={"width": 1440, "height": 800},
        )
        page = await context.new_page()

        try:
            # ─────────────────────────────────────────────────────────────
            # PASSO 1: Login — id.neogrid.com
            # ─────────────────────────────────────────────────────────────
            await page.goto(
                "https://id.neogrid.com/login/?lang=pt",
                wait_until="networkidle",
                timeout=30000
            )

            # Preenche e-mail
            await page.fill("input#login-form_email", email)
            await page.click("button#login_btn_continue_pre_check")

            # ─────────────────────────────────────────────────────────────
            # PASSO 2: Senha — platform.neogrid.com (Keycloak)
            # ─────────────────────────────────────────────────────────────
            await page.wait_for_selector("input[type='password']", timeout=15000)
            await page.fill("input[type='password']", password)
            await page.click("button[type='submit']")
            await page.wait_for_load_state("networkidle", timeout=20000)

            # ─────────────────────────────────────────────────────────────
            # PASSO 3: Portal — clicar em "EDI Logístico > Acessar"
            # ─────────────────────────────────────────────────────────────
            await page.wait_for_selector(
                "button#gtm-btn-access-EDI_Logístico",
                timeout=15000
            )
            await page.click("button#gtm-btn-access-EDI_Logístico")

            # Modal "Mudar organização" → clicar em Acessar
            await page.wait_for_selector(
                "button#gtm-btn-modal-access-organization-confirm",
                timeout=10000
            )

            # Aguarda nova aba abrir (my.neogrid.com)
            async with context.expect_page() as new_page_info:
                await page.click("button#gtm-btn-modal-access-organization-confirm")

            edi_page = await new_page_info.value
            await edi_page.wait_for_load_state("networkidle", timeout=20000)

            # ─────────────────────────────────────────────────────────────
            # PASSO 4: my.neogrid.com → "Acessar antigo EDI"
            # ─────────────────────────────────────────────────────────────
            # Clicar no menu lateral "Acessar antigo EDI"
            await edi_page.wait_for_selector(
                "text=Acessar antigo EDI",
                timeout=15000
            )

            # Nova aba será aberta com o antigo EDI
            async with context.expect_page() as old_edi_info:
                await edi_page.click("text=Acessar antigo EDI")

            old_edi = await old_edi_info.value
            await old_edi.wait_for_load_state("networkidle", timeout=20000)

            # ─────────────────────────────────────────────────────────────
            # PASSO 5: edi.neogrid.com — Caixa de Entrada
            # URL: https://edi.neogrid.com/mercador/summaryFrame.jsp
            # ─────────────────────────────────────────────────────────────
            await old_edi.wait_for_selector(
                'a[href="javascript:top.Navegacao.goInbox();"]',
                timeout=15000
            )
            await old_edi.click('a[href="javascript:top.Navegacao.goInbox();"]')
            await old_edi.wait_for_load_state("networkidle", timeout=15000)
            await asyncio.sleep(2)  # aguarda iframe Transacao carregar

            # ─────────────────────────────────────────────────────────────
            # PASSO 6: Preencher data atual e pesquisar
            # Tudo dentro do iframe "Transacao"
            # ─────────────────────────────────────────────────────────────
            transacao_frame = old_edi.frame(name="Transacao")
            if not transacao_frame:
                raise Exception("iframe Transacao não encontrado")

            # Aguarda o filtro carregar
            await transacao_frame.wait_for_selector(
                "input#iniCreationDateFilter",
                timeout=15000
            )

            # Preenche Data Criação Inicial = hoje
            await transacao_frame.fill("input#iniCreationDateFilter", today)
            await transacao_frame.press("input#iniCreationDateFilter", "Tab")

            # Preenche Data Criação Final = hoje
            await transacao_frame.fill("input#endCreationDateFilter", today)
            await transacao_frame.press("input#endCreationDateFilter", "Tab")

            # Clica em Pesquisar
            await transacao_frame.click('a[onclick="adjustDocumentTypeFilter()"]')
            await old_edi.wait_for_load_state("networkidle", timeout=20000)
            await asyncio.sleep(2)

            # ─────────────────────────────────────────────────────────────
            # PASSO 7: Identificar TXTs não lidos e baixar
            # Coluna índice 6 = "Leitura": valor "Lido" ou "Não Lido"
            # ─────────────────────────────────────────────────────────────

            # Re-obter o frame após a pesquisa
            transacao_frame = old_edi.frame(name="Transacao")

            await transacao_frame.wait_for_selector("table tr td", timeout=15000)

            # Coletar todas as linhas da tabela de resultados
            rows = await transacao_frame.query_selector_all("table tr")

            unread_save_links = []

            for row in rows:
                cells = await row.query_selector_all("td")
                if len(cells) < 7:
                    continue  # pula header e linhas vazias

                # Coluna índice 6 = Leitura
                leitura_cell = cells[6]
                leitura_text = (await leitura_cell.inner_text()).strip()

                # Considera "não lido" se NÃO contiver a palavra "Lido"
                if "Lido" not in leitura_text:
                    # Busca o link doSave nessa linha
                    save_links = await row.query_selector_all("a[onclick^='doSave(']")
                    for link in save_links:
                        onclick = await link.get_attribute("onclick")
                        unread_save_links.append({
                            "link": link,
                            "onclick": onclick
                        })

            if not unread_save_links:
                return {
                    "success": True,
                    "date": today,
                    "message": "Nenhum documento não lido encontrado para hoje.",
                    "total_downloaded": 0,
                    "files": [],
                    "errors": [],
                }

            # ─────────────────────────────────────────────────────────────
            # PASSO 8: Baixar cada TXT não lido
            # ─────────────────────────────────────────────────────────────
            for item in unread_save_links:
                try:
                    async with old_edi.expect_download(timeout=20000) as dl_info:
                        await item["link"].click()

                    download = await dl_info.value
                    filename = download.suggested_filename or f"doc_{item['onclick']}.txt"
                    filepath = DOWNLOAD_DIR / filename

                    await download.save_as(str(filepath))

                    with open(filepath, "rb") as f:
                        content = f.read()

                    downloaded_files.append({
                        "filename": filename,
                        "content_base64": base64.b64encode(content).decode("utf-8"),
                        "size_bytes": len(content),
                        "downloaded_at": datetime.now().isoformat(),
                        "onclick": item["onclick"],
                    })

                    os.remove(filepath)
                    await asyncio.sleep(0.5)

                except PlaywrightTimeout:
                    errors.append({
                        "error": "Timeout ao baixar",
                        "onclick": item.get("onclick")
                    })
                except Exception as e:
                    errors.append({
                        "error": str(e),
                        "onclick": item.get("onclick")
                    })

            return {
                "success": True,
                "date": today,
                "total_downloaded": len(downloaded_files),
                "files": downloaded_files,
                "errors": errors,
            }

        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "date": today,
                "files": [],
                "errors": errors,
            }
        finally:
            await browser.close()
