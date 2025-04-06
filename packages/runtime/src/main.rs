mod build_firefox;
mod bootstrap_firefox;

use anyhow::Context;
use futures_util::StreamExt;
use indicatif::{ProgressBar, ProgressStyle};
use simple_logger::SimpleLogger;
use std::cmp::min;
use std::fs::File;
use std::io::Write;
use std::path::PathBuf;
use std::time::Duration;
use tempfile::Builder;
use tokio::time::timeout;

type Result<T> = std::result::Result<T, anyhow::Error>;

async fn download_firefox_source(version: &str) -> Result<PathBuf> {
    log::debug!("Downloading firefox source code for version {}", version);

    let url = format!(
        "https://archive.mozilla.org/pub/firefox/releases/{}/source/firefox-{}.source.tar.xz",
        version, version
    );

    let tmp_dir = Builder::new()
        .prefix("warpfox")
        .tempdir()
        .context("Failed to create temporary directory")?;

    // Add timeout for network operations
    let response = timeout(Duration::from_secs(60), reqwest::get(&url))
        .await
        .context("Request timed out")??
        .error_for_status()
        .context(format!("Failed to GET from '{}'", &url))?;

    let total_size = response
        .content_length()
        .ok_or_else(|| anyhow::anyhow!("Failed to get content length from '{}'", &url))?;

    let pb = ProgressBar::new(total_size);
    pb.set_style(
        ProgressStyle::default_bar()
            .template("{msg}\n{spinner:.green} [{elapsed_precise}] [{wide_bar:.cyan/blue}] {bytes}/{total_bytes} ({bytes_per_sec}, {eta})")
            .context("Failed to create progress bar style")?
            .progress_chars("#>-")
    );
    pb.set_message(format!("Downloading {}", url));

    let mut downloaded: u64 = 0;
    let mut stream = response.bytes_stream();

    let fname = url
        .rsplit('/')
        .next()
        .context(format!("Failed to get filename from '{}'", &url))?;
    let fname = tmp_dir.path().join(fname);
    let mut dest = File::create(&fname).context("Failed to create file")?;

    while let Some(item) = stream.next().await {
        let chunk = item.context("Error while downloading file")?;
        dest.write_all(&chunk)
            .context("Error while writing to file")?;
        let new = min(downloaded + (chunk.len() as u64), total_size);
        downloaded = new;
        pb.set_position(new);
    }

    pb.finish();
    Ok(tmp_dir.into_path())
}

fn unpack_firefox_source(source_tar: PathBuf) -> Result<PathBuf> {
    log::debug!("Unpacking firefox source code");

    let output = PathBuf::from("engine");
    std::fs::create_dir_all(&output).context("Failed to create 'engine' directory")?;

    let status = std::process::Command::new("tar")
        .arg("-xf")
        .arg(&source_tar)
        .arg("--strip-components=1")
        .arg("-C")
        .arg(&output)
        .status()
        .context("Failed to execute tar command")?;

    if !status.success() {
        return Err(anyhow::anyhow!(
            "tar command failed with status: {}",
            status
        ));
    }

    Ok(output)
}

fn cleanup(source_tar_dir: &PathBuf) -> Result<()> {
    log::info!("Cleaning up");
    if source_tar_dir.exists() {
        std::fs::remove_dir_all(source_tar_dir).context("Failed to remove temporary directory")?;
    }
    Ok(())
}

#[tokio::main]
async fn main() -> Result<()> {
    // Set up signal handling for graceful shutdown
    let (shutdown_tx, shutdown_rx) = tokio::sync::oneshot::channel();

    tokio::spawn(async move {
        if let Ok(_) = tokio::signal::ctrl_c().await {
            let _ = shutdown_tx.send(());
        }
    });

    SimpleLogger::new()
        .with_colors(true)
        .without_timestamps()
        .init()
        .context("Failed to initialize logger")?;

    let manifest: serde_json::Value =
        serde_json::from_str(include_str!("../../warpfox/firefox.json"))
            .context("Failed to parse firefox.json")?;
    let version = manifest["version"]
        .as_str()
        .context("Missing 'version' in firefox.json")?;

    log::info!("Starting runtime for firefox v{}", version);

    let source_tar_dir = download_firefox_source(version).await?;
    let source_tar = source_tar_dir.join(format!("firefox-{}.source.tar.xz", version));
    log::info!("Downloaded source code to {:?}", source_tar);

    let source_dir = unpack_firefox_source(source_tar)?;
    log::info!("Unpacked source code to {:?}", source_dir);

    crate::bootstrap_firefox::bootstrap_firefox(&source_dir)
        .await
        .context("Failed to bootstrap Firefox")?;

    crate::build_firefox::build_firefox(&source_dir)
        .await
        .context("Failed to build Firefox")?;

    cleanup(&source_tar_dir)?;

    // Handle shutdown signal
    tokio::select! {
        _ = shutdown_rx => {
            log::info!("Received shutdown signal, cleaning up...");
            cleanup(&source_tar_dir)?;
        }
        _ = async {} => {}
    }

    Ok(())
}
