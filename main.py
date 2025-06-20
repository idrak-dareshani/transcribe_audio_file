"""
Enhanced Audio Transcription and Summarization Pipeline for Urdu and English

This module provides functionality to:
1. Transcribe Urdu and English audio files using OpenAI Whisper
2. Process transcriptions into sentences using language-specific approaches
3. Generate summaries using appropriate multilingual models
"""

import os
import re
import time
import logging
import unicodedata
from pathlib import Path
from typing import List, Generator, Optional, Dict, Tuple

import whisper
from transformers import pipeline

def check_dependencies():
    """Check for required Python packages and models."""
    import importlib
    required_packages = [
        "os", "re", "time", "logging", "pathlib",
        "transformers", "torch", "whisper", "unicodedata"
    ]
    missing = []
    for pkg in required_packages:
        try:
            importlib.import_module(pkg)
        except ImportError:
            missing.append(pkg)
    if missing:
        raise ImportError(
            f"Missing required packages: {', '.join(missing)}. "
            "Please install them before running this script."
        )

class AudioProcessor:
    """Handles multilingual audio transcription and text processing pipeline."""
    
    def __init__(self, model_size: str = "medium"):
        """
        Initialize the AudioProcessor.
        
        Args:
            model_size: Whisper model size ('tiny', 'base', 'small', 'medium', 'large')
        """
        self.model_size = model_size
        self.logger = self._setup_logger()
        
        # Initialize models
        self.whisper_model = None
        self.summarizer = None
        
        # Create necessary directories
        self._create_directories()
        
        # Language-specific patterns
        self.sentence_patterns = {
            'ur': r'[۔؟!]',  # Urdu sentence endings
            'en': r'[.!?]',   # English sentence endings
        }
        
        # Stop words for key phrase extraction
        self.stop_words = {
            'ur': {
                'اور', 'کا', 'کے', 'کی', 'میں', 'سے', 'کو', 'نے', 'ہے', 'ہیں', 'تھا', 'تھے', 
                'یہ', 'وہ', 'جو', 'کہ', 'لیے', 'ساتھ', 'بھی', 'تو', 'پر', 'اس', 'ان', 'ایک'
            },
            'en': {
                'the', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'with', 'by',
                'a', 'an', 'is', 'are', 'was', 'were', 'be', 'been', 'have', 'has', 'had',
                'do', 'does', 'did', 'will', 'would', 'could', 'should', 'may', 'might',
                'this', 'that', 'these', 'those', 'i', 'you', 'he', 'she', 'it', 'we', 'they'
            }
        }
        
    def _setup_logger(self) -> logging.Logger:
        """Set up logging configuration."""
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler('audio_processing.log', encoding='utf-8'),
                logging.StreamHandler()
            ]
        )
        return logging.getLogger(__name__)
    
    def _create_directories(self) -> None:
        """Create necessary directories if they don't exist."""
        directories = ['audio', 'transcripts', 'analysis']
        for directory in directories:
            Path(directory).mkdir(exist_ok=True)
            
    def _load_whisper_model(self) -> whisper.Whisper:
        """Load Whisper model with caching."""
        if self.whisper_model is None:
            self.logger.info(f"Loading Whisper model: {self.model_size}")
            self.whisper_model = whisper.load_model(self.model_size)
        return self.whisper_model
    
    def _load_summarizer(self, language: str = "ur"):
        """
        Load appropriate summarization model based on language.
        
        Args:
            language: Target language ('ur' for Urdu, 'en' for English)
        """
        if self.summarizer is None:
            self.logger.info(f"Loading summarization model for language: {language}")
            try:
                if language == "en":
                    # Use BART for English - better performance
                    model_name = "facebook/bart-large-cnn"
                    self.logger.info("Loading BART model for English")
                else:
                    # Use mT5 for Urdu and other languages
                    model_name = "google/mt5-small"
                    self.logger.info("Loading mT5 model for Urdu/multilingual")
                
                self.summarizer = pipeline(
                    "summarization", 
                    model=model_name,
                    tokenizer=model_name,
                    device=0 if self._is_gpu_available() else -1
                )
            except Exception as e:
                self.logger.warning(f"Failed to load preferred model: {e}")
                # Fallback to BART
                self.logger.info("Falling back to BART model")
                self.summarizer = pipeline(
                    "summarization", 
                    model="facebook/bart-large-cnn",
                    device=0 if self._is_gpu_available() else -1
                )
        return self.summarizer
    
    def _is_gpu_available(self) -> bool:
        """Check if GPU is available for processing."""
        try:
            import torch
            return torch.cuda.is_available()
        except ImportError:
            return False

    def normalize_urdu(self, text: str) -> str:
        text = unicodedata.normalize("NFKC", text)
        text = text.replace("ک", "ك").replace("ی", "ي")
        return re.sub(r'\s+', ' ', text.strip())

    def detect_language(self, text: str) -> str:
        """
        Simple language detection based on character sets.
        
        Args:
            text: Text to analyze
            
        Returns:
            Language code ('ur' or 'en')
        """
        # Count Urdu/Arabic characters
        urdu_chars = len(re.findall(r'[\u0600-\u06FF]', text))
        
        # Count English characters
        english_chars = len(re.findall(r'[a-zA-Z]', text))
        
        # Determine primary language
        if urdu_chars > english_chars:
            return 'ur'
        else:
            return 'en'
    
    def transcribe_audio(self, audio_file: str, language: str = "ur", 
                        output_file: str = None) -> str:
        """
        Transcribe audio file to text with multilingual support.
        
        Args:
            audio_file: Path to audio file
            language: Language code for transcription (default: 'ur' for Urdu)
            output_file: Path to save transcription (auto-generated if None)
            auto_detect: Whether to auto-detect language after initial transcription
            
        Returns:
            str = transcribed_text
        """
        if not os.path.exists(audio_file):
            raise FileNotFoundError(f"Audio file not found: {audio_file}")
        
        model = self._load_whisper_model()
        
        # Generate output filename if not provided
        if output_file is None:
            base_name = Path(audio_file).stem
            output_file = f"transcripts/{base_name}_transcription.txt"
        
        self.logger.info(f"Starting transcription of {audio_file} (language: {language})")
        start_time = time.time()
        
        try:
            # Enhanced options for better transcription
            result = model.transcribe(
                audio_file, 
                language=language,
                fp16=False,  # Better for CPU processing
                verbose=True,
                word_timestamps=True  # Get word-level timestamps
            )
            
            transcription = result["text"]
            transcription = self.normalize_urdu(transcription) if language == 'ur' else transcription
            
            # Post-process transcription based on language
            transcription = self._clean_text(transcription, language)
            
            # Calculate processing time
            elapsed = time.time() - start_time
            minutes = int(elapsed // 60)
            seconds = int(elapsed % 60)
            self.logger.info(f"Transcription completed in {minutes}m {seconds}s")
            
            # Save transcription with UTF-8 encoding
            with open(output_file, "w", encoding="utf-8") as f:
                f.write(f"Language: {language}\n")
                f.write(f"Transcription:\n{transcription}")
            
            # Also save detailed results if available
            if "segments" in result:
                detailed_file = output_file.replace(".txt", "_detailed.txt")
                with open(detailed_file, "w", encoding="utf-8") as f:
                    f.write(f"Language: {language}\n")
                    f.write("Detailed Transcription with Timestamps:\n\n")
                    for segment in result["segments"]:
                        f.write(f"[{segment['start']:.2f}s - {segment['end']:.2f}s]: {segment['text']}\n")
                self.logger.info(f"Detailed transcription saved to {detailed_file}")
            
            self.logger.info(f"Transcription saved to {output_file}")
            return transcription
            
        except Exception as e:
            self.logger.error(f"Error during transcription: {str(e)}")
            raise
    
    def _clean_text(self, text: str, language: str) -> str:
        """
        Clean and format text based on language.
        
        Args:
            text: Raw transcribed text
            language: Language code
            
        Returns:
            Cleaned text
        """
        # Remove extra whitespace
        text = re.sub(r'\s+', ' ', text.strip())
        
        if language == 'ur':
            # Urdu-specific cleaning
            text = re.sub(r'\s+([۔؟!])', r'\1', text)  # Remove space before punctuation
            text = re.sub(r'([۔؟!])\s*', r'\1 ', text)  # Ensure space after punctuation
            # Keep Urdu, Arabic, and basic punctuation
            text = re.sub(r'[^\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF\s۔؟!،٫٬\w]', '', text)
        else:
            # English-specific cleaning
            text = re.sub(r'\s+([.!?])', r'\1', text)  # Remove space before punctuation
            text = re.sub(r'([.!?])\s*', r'\1 ', text)  # Ensure space after punctuation
            # Basic punctuation cleanup for English
            text = re.sub(r'[^\w\s.!?,:;\'\"()-]', '', text)
        
        return text.strip()

    def process_sentences(self, text: str, language: str, 
                               output_file: str = None) -> List[str]:
        """
        Process text into sentences using language-specific regex patterns.
        
        Args:
            text: Input text to process
            language: Language code
            output_file: Path to save sentences (auto-generated if None)
            
        Returns:
            List of sentences
        """
        if output_file is None:
            output_file = f"analysis/sentences_{language}.txt"

        processed_sentences = []

        if language == 'ur':
            # Use regex for Urdu 
            self.logger.info("Using regex for Urdu sentence segmentation")
            processed_sentences = self._regex_sentence_split(text, language)
        
        else:
            # Use regex for English
            self.logger.info("Using regex for English sentence segmentation")
            processed_sentences = self._regex_sentence_split(text, language)
        
        # Save sentences
        with open(output_file, 'w', encoding="utf-8") as f:
            f.write(f"Language: {language}\n")
            f.write(f"Total sentences: {len(processed_sentences)}\n")
            for i, sentence in enumerate(processed_sentences, 1):
                f.write(f"{i}. {sentence.strip()}\n")
        
        self.logger.info(f"Processed {len(processed_sentences)} sentences for {language}, saved to {output_file}")
        return processed_sentences

    def _regex_sentence_split(self, text: str, language: str) -> List[str]:
        """
        Helper method for regex-based sentence splitting.
        
        Args:
            text: Input text
            language: Language code
            
        Returns:
            List of sentences
        """
        # Get language-specific pattern
        pattern = self.sentence_patterns.get(language, self.sentence_patterns['en'])
        
        # Split on sentence endings
        sentences = re.split(pattern, text)
        
        # Clean and filter sentences
        processed_sentences = []
        for sentence in sentences:
            sentence = sentence.strip()
            if sentence and len(sentence.split()) >= 3:  # Minimum 3 words
                processed_sentences.append(sentence)
        
        # Add back sentence endings (except for the last one)
        final_sentences = []
        ending_char = '۔' if language == 'ur' else '.'
        
        for i, sentence in enumerate(processed_sentences[:-1]):
            # Find the original ending punctuation
            next_pos = text.find(sentence) + len(sentence)
            if next_pos < len(text) and text[next_pos] in ('۔؟!' if language == 'ur' else '.!?'):
                ending = text[next_pos]
                final_sentences.append(sentence + ending)
            else:
                final_sentences.append(sentence + ending_char)
        
        # Add the last sentence without ending if it exists
        if processed_sentences:
            final_sentences.append(processed_sentences[-1])
        
        return final_sentences

    def extract_key_phrases(self, text: str, language: str) -> List[str]:
        """
        Enhanced key phrase extraction using UrduHack for Urdu text processing.
        
        Args:
            text: Input text
            language: Language code
            
        Returns:
            List of key phrases
        """
        if language == 'ur':
            # Extract Urdu words
            words = re.findall(r'[\u0600-\u06FF]{2,}', text)
        else:
            # Extract English words
            words = re.findall(r'\b[a-zA-Z]{2,}\b', text.lower())
        
        # Get language-specific stop words
        stop_words = self.stop_words.get(language)
        
        # Count word frequency
        word_freq = {}
        for word in words:
            if word not in stop_words and len(word) > 2:
                word_freq[word] = word_freq.get(word, 0) + 1
        
        # Get top words
        top_words = sorted(word_freq.items(), key=lambda x: x[1], reverse=True)[:10]
        
        return [word for word, word_freq in top_words]
    
    def chunk_text(self, text: str, language: str, max_words: int = None) -> Generator[str, None, None]:
        """
        Split text into chunks for processing based on language.
        
        Args:
            text: Text to chunk
            language: Language code
            max_words: Maximum words per chunk (auto-adjusted by language if None)
            
        Yields:
            Text chunks
        """
        if max_words is None:
            # Adjust chunk size based on language
            max_words = 300 if language == 'ur' else 500
        
        words = text.split()
        for i in range(0, len(words), max_words):
            chunk = ' '.join(words[i:i + max_words])
            if chunk.strip():
                yield chunk
    
    def summarize_text(self, text: str, language: str, max_length: int = None, 
                      min_length: int = None) -> str:
        """
        Summarize text using appropriate models based on language.
        
        Args:
            text: Text to summarize
            language: Language code
            max_length: Maximum summary length (auto-adjusted if None)
            min_length: Minimum summary length (auto-adjusted if None)
            
        Returns:
            Summarized text
        """
        if not text.strip():
            return "⚠️ Empty input. Skipped."
        
        word_count = len(text.split())
        if word_count < 20:
            return "ℹ️ Text too short to summarize. Consider keeping as-is."
        
        # Adjust parameters based on language
        if max_length is None:
            max_length = 8 if language == 'ur' else 150
        if min_length is None:
            min_length = 3 if language == 'ur' else 50
        
        summarizer = self._load_summarizer(language)
        summaries = []
        
        self.logger.info(f"Summarizing {language} text with {word_count} words")
        
        try:
            for i, chunk in enumerate(self.chunk_text(text, language), 1):
                try:
                    self.logger.debug(f"Processing chunk {i}")
                    
                    # For mT5, we might need to add a prefix
                    if (hasattr(summarizer.model, 'config') and 
                        'mt5' in str(summarizer.model.config).lower()):
                        summary_input = f"summarize: {chunk}"
                    else:
                        summary_input = chunk
                    
                    summary = summarizer(
                        summary_input, 
                        max_length=max_length, 
                        min_length=min_length, 
                        do_sample=False
                    )
                    summaries.append(summary[0]['summary_text'])
                    
                except Exception as e:
                    error_msg = f"❌ Error summarizing chunk {i}: {str(e)}"
                    self.logger.error(error_msg)
                    # Fallback: return first few sentences
                    if language == 'ur':
                        sentences = chunk.split('۔')[:3]
                        fallback_summary = '۔'.join(sentences[:2]) + '۔'
                    else:
                        sentences = chunk.split('.')[:3]
                        fallback_summary = '.'.join(sentences[:2]) + '.'
                    summaries.append(f"📝 {fallback_summary}")
            
            return "\n\n".join(summaries)
            
        except Exception as e:
            self.logger.error(f"Summarization failed: {str(e)}")
            # Return first few sentences as fallback
            if language == 'ur':
                sentences = text.split('۔')[:3]
                return '۔'.join(sentences[:2]) + '۔'
            else:
                sentences = text.split('.')[:3]
                return '.'.join(sentences[:2]) + '.'
    
    def process_pipeline(self, file_name: str, language: str = "ur") -> dict:
        """
        Run the complete multilingual audio processing pipeline.
        
        Args:
            file_name: Name of the audio file (without extension)
            language: Language code for transcription (default: 'ur')
            auto_detect: Whether to auto-detect language
            
        Returns:
            Dictionary with processing results
        """
        results = {}
        
        try:
            # Step 1: Transcribe audio
            audio_file = f"audio/{file_name}.mp3"
            transcription = self.transcribe_audio(audio_file, language)
            results['transcription'] = transcription
            results['language'] = language
            results['word_count'] = len(transcription.split())
            
            # Step 2: Process sentences using regex
            sentences = self.process_sentences(transcription, language)
            results['sentences'] = sentences
            results['sentence_count'] = len(sentences)
            
            # Step 3: Extract key phrases
            key_phrases = self.extract_key_phrases(transcription, language)
            results['key_phrases'] = key_phrases
            
            # Step 4: Generate summary
            combined_text = " ".join(sentences)
            summary = self.summarize_text(combined_text, language)
            
            # Save summary
            summary_file = f"analysis/{file_name}_{language}_summary.txt"
            with open(summary_file, "w", encoding="utf-8") as f:
                if language == 'ur':
                    f.write("=== خلاصہ (Summary) ===\n")
                    f.write(summary)
                    f.write("\n\n=== اہم الفاظ (Key Phrases) ===\n")
                else:
                    f.write("=== Summary ===\n")
                    f.write(summary)
                    f.write("\n\n=== Key Phrases ===\n")
                f.write(", ".join(key_phrases))
            
            results['summary'] = summary
            results['summary_file'] = summary_file
            results['status'] = 'success'
            
            self.logger.info(f"Multilingual audio processing pipeline completed successfully for {language}")
            
        except Exception as e:
            error_msg = f"Pipeline failed: {str(e)}"
            self.logger.error(error_msg)
            results['status'] = 'error'
            results['error'] = error_msg
            
        return results

    def process_batch(self, audio_dir: str, language: str = "ur") -> Dict[str, dict]:
        """
        Process all audio files in a directory.
        
        Args:
            audio_dir: Directory containing audio files
            language: Language code for transcription
            auto_detect: Whether to auto-detect language
            
        Returns:
            Dictionary mapping file names to their processing results
        """
        results = {}
        audio_path = Path(audio_dir)
        for audio_file in audio_path.glob("*.mp3"):
            file_name = audio_file.stem
            try:
                self.logger.info(f"Processing file: {audio_file}")
                results[file_name] = self.process_pipeline(file_name, language)
            except Exception as e:
                results[file_name] = {"status": "error", "error": str(e)}
        return results

def main():
    """Main function to run the multilingual audio processing pipeline."""

    # Check for required dependencies
    check_dependencies()

    # Configuration
    batch_mode = False  # Set to True to process all files in 'audio' directory
    audio_dir = "audio"  # Directory containing audio files
    language = "ur"  # Default to Urdu, but can be "en" for English
    model_size = "medium"  # Recommended for better accuracy
    
    # Initialize processor
    processor = AudioProcessor(model_size=model_size)
        
    if batch_mode:
        # Run batch processing
        results = processor.process_batch(audio_dir, language)
        
        # Print results summary
        for file_name, result in results.items():
            if result['status'] == 'success':
                lang_name = "Urdu" if result['language'] == 'ur' else "English"
                print(f"✅ {lang_name} audio processing completed for {file_name}!")
                print(f"🗣️ Detected language: {lang_name}")
                print(f"📊 Word count: {result['word_count']}")
                print(f"📝 Processed {result['sentence_count']} sentences")
                print(f"🔑 Key phrases: {', '.join(result['key_phrases'][:5])}")
                print(f"📄 Summary saved to {result['summary_file']}\n")
            else:
                print(f"❌ Processing failed for {file_name}: {result['error']}\n")
                
    else:
        # Single file processing example
        file_name = "001 - SURAH AL-FATIAH"  # Your audio file name (without extension)
        
        # Run pipeline
        results = processor.process_pipeline(file_name, language)
        
        # Print results
        if results['status'] == 'success':
            lang_name = "Urdu" if results['language'] == 'ur' else "English"
            print(f"✅ {lang_name} audio processing completed successfully!")
            print(f"🗣️ Detected language: {lang_name}")
            print(f"📊 Word count: {results['word_count']}")
            print(f"📝 Processed {results['sentence_count']} sentences")
            print(f"🔑 Key phrases: {', '.join(results['key_phrases'][:5])}")
            print(f"📄 Summary saved to {results['summary_file']}")
            
            # Display first few lines of summary
            print(f"\n📋 Summary preview:")
            summary_preview = results['summary'][:200] + "..." if len(results['summary']) > 200 else results['summary']
            print(summary_preview)
            
        else:
            print(f"❌ Processing failed: {results['error']}")


if __name__ == "__main__":
    main()