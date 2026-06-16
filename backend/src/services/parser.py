import fitz  # PyMuPDF
import io
import logging

logger = logging.getLogger(__name__)

class PDFParser:
    @staticmethod
    def parse_pdf(file_bytes: bytes) -> list[dict]:
        """
        Parses a PDF file from bytes.
        Returns a list of dictionaries with text and metadata per page.
        """
        pages = []
        try:
            # Load PDF from memory bytes stream
            pdf_stream = io.BytesIO(file_bytes)
            doc = fitz.open(stream=pdf_stream, filetype="pdf")
            total_pages = len(doc)
            
            logger.info(f"Successfully opened PDF with {total_pages} pages.")

            for page_num in range(total_pages):
                page = doc.load_page(page_num)
                text = page.get_text("text") # Extract plain text
                
                # We can also extract basic layout metadata if needed
                page_info = {
                    "page_number": page_num + 1,
                    "text": text.strip(),
                    "metadata": {
                        "page": page_num + 1,
                        "total_pages": total_pages,
                        "dimensions": {
                            "width": page.rect.width,
                            "height": page.rect.height
                        }
                    }
                }
                pages.append(page_info)
                
            doc.close()
        except Exception as e:
            logger.error(f"Error parsing PDF: {e}")
            raise e

        return pages
